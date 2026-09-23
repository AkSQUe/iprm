"""Розділ сертифікатів у кабінеті тренера."""
import io
import json
import tempfile
from html.parser import HTMLParser
from itertools import count
from unittest.mock import patch

import pytest
from PIL import Image

from app.extensions import db
from app.models.media_file import MediaFile
from app.models.site_settings import SiteSettings
from app.services import lecturer_certificates as lc_svc
from app.services.trainer_links import set_trainers
from tests.test_trainer_cabinet._factories import (
    login, make_course, make_instance, make_trainer, make_user,
)


@pytest.fixture
def media_root(app):
    """Тимчасова тека для файлів медіа-реєстру -- як у test_trainer_media.py."""
    prev = app.config.get('MEDIA_FOLDER')
    app.config['MEDIA_FOLDER'] = tempfile.mkdtemp()
    yield app.config['MEDIA_FOLDER']
    app.config['MEDIA_FOLDER'] = prev


def _png():
    buf = io.BytesIO()
    Image.new('RGB', (700, 500), (60, 120, 90)).save(buf, 'PNG')
    buf.seek(0)
    return buf


class _InputValueFinder(HTMLParser):
    """Атрибут value заданого <input id="..."> -- розбирає так само, як
    браузер (включно з розкодуванням &#39; тощо), на відміну від regex/
    текстового пошуку, який не бачить, де саме обривається атрибут."""

    def __init__(self, field_id):
        super().__init__()
        self.field_id = field_id
        self.value = None

    def handle_starttag(self, tag, attrs):
        if tag != 'input':
            return
        d = dict(attrs)
        if d.get('id') == self.field_id:
            self.value = d.get('value')

def _flashes(client):
    """Тексти flash-повідомлень у сесії. На сторінці вони лежать у JSON для
    тостів (tojson екранує кирилицю в \\uXXXX), тож шукати їх у HTML
    ненадійно -- читаємо саму сесію до редіректу."""
    with client.session_transaction() as sess:
        return [message for _category, message in sess.get('_flashes', [])]


# Власний лічильник номерів заходів БПР, як у test_lecturer_certificates.py:
# issue_for_instance комітить сам, а деякі тести тут викликають фабрику
# двічі (свій + чужий сертифікат), тож номери мають не збігатися в межах
# одного тесту.
_event_numbers = count(6000000)


@pytest.fixture(autouse=True)
def bpr_settings(app):
    """Номер провайдера БПР -- без нього issue_for_instance падає ще до
    видачі жодного сертифіката (_bpr_number_inputs), а брифу цей рядок
    бракувало."""
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    db.session.flush()


def _trainer_with_certificate():
    user = make_user()
    trainer = make_trainer(user, name='Сертифікований Т.')
    course = make_course('Курс із сертифікатом')
    course.bpr_event_number = str(next(_event_numbers))
    set_trainers(course, [trainer.id])
    course.bpr_lecturer_points = 6
    inst = make_instance(course, days=-3, status='completed')
    db.session.commit()
    cert = lc_svc.issue_for_instance(inst)[0]
    return user, trainer, cert


def test_anonymous_redirected_to_login(client):
    resp = client.get('/trainer/certificates')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_user_without_card_gets_404(client):
    login(client, make_user())
    assert client.get('/trainer/certificates').status_code == 404


def test_section_lists_own_certificate(client):
    user, _, cert = _trainer_with_certificate()
    login(client, user)
    resp = client.get('/trainer/certificates')
    assert resp.status_code == 200
    assert cert.number.encode() in resp.data


def test_section_does_not_list_foreign_certificate(client):
    _, _, foreign = _trainer_with_certificate()
    other_user = make_user()
    make_trainer(other_user, name='Чужий Т.')
    login(client, other_user)
    resp = client.get('/trainer/certificates')
    assert resp.status_code == 200
    assert foreign.number.encode() not in resp.data


def test_download_own_certificate_returns_pdf(client):
    user, _, cert = _trainer_with_certificate()
    login(client, user)
    resp = client.get(f'/trainer/certificates/{cert.id}/download')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.data[:4] == b'%PDF'


def test_download_foreign_certificate_is_404(client):
    _, _, foreign = _trainer_with_certificate()
    other_user = make_user()
    make_trainer(other_user, name='Чужий Т. 2')
    login(client, other_user)
    resp = client.get(f'/trainer/certificates/{foreign.id}/download')
    assert resp.status_code == 404


def test_report_error_notifies_curator(client):
    from types import SimpleNamespace
    from unittest.mock import patch

    user, _, cert = _trainer_with_certificate()
    login(client, user)
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate_complaint',
               return_value=[SimpleNamespace(status='pending')]) as notify:
        resp = client.post(f'/trainer/certificates/{cert.id}/report',
                           data={'message': 'Помилка в ПІБ'})
    assert resp.status_code == 302
    assert notify.called
    assert _flashes(client) == ['Повідомлення надіслано куратору']


def test_report_without_recipients_does_not_claim_success(client):
    """Нуль отримувачів: notify_admins_with_template повертає [] -- лист не
    пішов нікому, і «надіслано куратору» було б неправдою."""
    from unittest.mock import patch

    user, _, cert = _trainer_with_certificate()
    login(client, user)
    with patch('app.services.notification_recipients.resolve', return_value=[]):
        resp = client.post(f'/trainer/certificates/{cert.id}/report',
                           data={'message': 'Помилка в ПІБ'})
    assert resp.status_code == 302
    flashes = _flashes(client)
    assert 'Повідомлення надіслано куратору' not in flashes
    assert any(m.startswith('Повідомлення не доставлено') for m in flashes)


def test_report_error_on_foreign_certificate_is_404(client):
    from unittest.mock import patch

    _, _, foreign = _trainer_with_certificate()
    other_user = make_user()
    make_trainer(other_user, name='Чужий Т. 3')
    login(client, other_user)
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate_complaint') as notify:
        resp = client.post(f'/trainer/certificates/{foreign.id}/report',
                           data={'message': 'X'})
    assert resp.status_code == 404
    assert not notify.called


# --- власні сертифікати (редагування тренером) --------------------------


def test_trainer_saves_own_regalia(client):
    """Тренер змінює підпис уже наявної позиції -- зберігається."""
    user = make_user()
    trainer = make_trainer(user, name='Регалійний Т.')
    trainer.certificates = [
        {'url': '/media/2026/06/a.webp', 'thumb': '/media/2026/06/a.webp',
         'caption': 'Старий підпис'},
    ]
    db.session.commit()
    login(client, user)
    payload = json.dumps([
        {'url': '/media/2026/06/a.webp', 'thumb': '/media/2026/06/a.webp',
         'caption': 'Диплом'},
    ])
    resp = client.post('/trainer/certificates',
                       data={'certificates': payload}, follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(trainer)
    assert len(trainer.certificates) == 1
    assert trainer.certificates[0]['caption'] == 'Диплом'


def test_new_item_without_media_id_is_rejected(client):
    """Нову картинку тренер додає лише завантаженням (воно дає media_id).
    Позиція без media_id, якої ще не було, -- це підроблений запит або
    посилання на чужий файл."""
    user = make_user()
    trainer = make_trainer(user, name='Підробний Т.')
    login(client, user)
    payload = json.dumps([
        {'url': '/media/2026/06/foreign.webp', 'caption': 'Не моє'},
    ])
    client.post('/trainer/certificates', data={'certificates': payload},
                follow_redirects=True)
    db.session.refresh(trainer)
    assert trainer.certificates in (None, [])


@pytest.mark.parametrize('form', [
    {},                               # поле відсутнє
    {'certificates': '[{"url": '},   # зламаний JSON
    {'certificates': '{"url": "/media/2026/06/a.webp"}'},  # не список
])
def test_unreadable_payload_changes_nothing(client, form):
    """Збій на боці браузера не має трактуватись як «стерти все»."""
    user = make_user()
    trainer = make_trainer(user, name='Незмінний Т.')
    saved = [{'url': '/media/2026/06/a.webp', 'thumb': '/media/2026/06/a.webp',
              'caption': 'Диплом'}]
    trainer.certificates = saved
    db.session.commit()
    login(client, user)
    resp = client.post('/trainer/certificates', data=form)
    assert resp.status_code == 302
    assert any(m.startswith('Не вдалося прочитати дані форми')
               for m in _flashes(client))
    db.session.refresh(trainer)
    assert trainer.certificates == saved


def test_foreign_media_id_is_not_hijacked(client, media_root):
    """Фінальна рецензія, C2: тренер Б підставляє media_id медіа тренера А.
    Без перевірки власника attach_trainer_media перепривʼязав би MediaFile
    до Б і фізично перейменував файл А під slug Б."""
    import os

    from app.models.trainer import Trainer

    user_a = make_user()
    trainer_a = make_trainer(user_a, name='Власник А.')
    login(client, user_a)
    uploaded = client.post('/trainer/certificates/upload',
                           data={'file': (_png(), 'a.png')},
                           content_type='multipart/form-data').get_json()
    client.post('/trainer/certificates', data={'certificates': json.dumps([{
        'url': uploaded['url'], 'thumb': uploaded['thumb'],
        'media_id': uploaded['media_id'], 'caption': 'Диплом А',
    }])}, follow_redirects=True)
    media = db.session.get(MediaFile, uploaded['media_id'])
    before = (media.entity_type, media.entity_id, media.file_path)
    assert before[:2] == ('trainer', trainer_a.id)
    db.session.refresh(trainer_a)
    url_a = trainer_a.certificates[0]['url']

    user_b = make_user()
    trainer_b = make_trainer(user_b, name='Нападник Б.')
    login(client, user_b)
    client.post('/trainer/certificates', data={'certificates': json.dumps([{
        'url': url_a, 'thumb': url_a, 'media_id': media.id, 'caption': 'Моє',
    }])}, follow_redirects=True)

    db.session.expire_all()
    media = db.session.get(MediaFile, uploaded['media_id'])
    assert (media.entity_type, media.entity_id, media.file_path) == before
    assert os.path.exists(media.abs_path)
    trainer_b = db.session.get(Trainer, trainer_b.id)
    assert not any(c.get('media_id') == media.id or c.get('url') == url_a
                   for c in (trainer_b.certificates or []))


def test_save_rejects_invalid_url(client):
    user = make_user()
    trainer = make_trainer(user, name='Невалідний Т.')
    login(client, user)
    payload = json.dumps([{'url': 'javascript:alert(1)', 'caption': 'X'}])
    client.post('/trainer/certificates', data={'certificates': payload},
                follow_redirects=True)
    db.session.refresh(trainer)
    assert trainer.certificates == []


def test_upload_requires_trainer_card(client):
    login(client, make_user())
    resp = client.post('/trainer/certificates/upload', data={
        'file': (io.BytesIO(b'x'), 'a.png')})
    assert resp.status_code == 404


def test_upload_returns_media_id(client, media_root):
    """Happy path завантаження -- досі був перевірений лише 404 без картки."""
    user = make_user()
    make_trainer(user, name='Завантажувач Т.')
    login(client, user)
    resp = client.post('/trainer/certificates/upload',
                       data={'file': (_png(), 'c.png')},
                       content_type='multipart/form-data')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['url'].startswith('/media/')
    assert data['media_id']


def test_saving_certificate_attaches_media_to_trainer(client, media_root):
    """Запобіжник проти втрати даних (рецензія задачі 10).

    Без trainer_service.attach_trainer_media файл, завантажений тренером,
    лишається без entity_type/entity_id і рано чи пізно фізично зникає під
    CLI media-prune-orphans (`app/cli.py`: вибирає MediaFile.entity_type
    IS NULL старші за --days і видаляє з диска), хоча сторінка тренера й
    далі показує його як наявний.
    """
    user = make_user()
    trainer = make_trainer(user, name='Привʼязаний Т.')
    login(client, user)
    uploaded = client.post('/trainer/certificates/upload',
                           data={'file': (_png(), 'c.png')},
                           content_type='multipart/form-data').get_json()
    payload = json.dumps([{
        'url': uploaded['url'], 'thumb': uploaded['thumb'],
        'media_id': uploaded['media_id'], 'caption': 'Диплом',
    }])
    resp = client.post('/trainer/certificates', data={'certificates': payload},
                       follow_redirects=True)
    assert resp.status_code == 200
    media = db.session.get(MediaFile, uploaded['media_id'])
    assert media.entity_type == 'trainer'
    assert media.entity_id == trainer.id
    assert media.usage_type == 'certificate'


def test_removing_item_clears_it_from_public_page(client):
    """Кабінет і публічна сторінка читають одне сховище, не два."""
    user = make_user()
    trainer = make_trainer(user, name='Прибиральний Т.')
    trainer.certificates = [
        {'url': '/media/2026/06/a.webp', 'thumb': '/media/2026/06/a.webp',
         'caption': 'Диплом'},
    ]
    db.session.commit()
    login(client, user)
    client.post('/trainer/certificates', data={'certificates': '[]'},
                follow_redirects=True)
    db.session.refresh(trainer)
    assert trainer.certificates == []


def test_trainer_cannot_write_foreign_certificates(client):
    user = make_user()
    make_trainer(user, name='Свій Т.')
    foreign = make_trainer(name='Чужий Т. 4')
    foreign.certificates = [
        {'url': '/media/2026/06/b.webp', 'thumb': '/media/2026/06/b.webp',
         'caption': 'Чуже'},
    ]
    db.session.commit()
    login(client, user)
    client.post('/trainer/certificates', data={'certificates': '[]'},
                follow_redirects=True)
    db.session.refresh(foreign)
    assert len(foreign.certificates) == 1


def test_own_certificates_field_survives_html_roundtrip(client):
    """Візуальна перевірка (раунд 2): tojson екранує лише ' -- призначений
    для <script>, не для атрибута в подвійних лапках. У подвійних лапках
    перша ж лапка з JSON обірвала б атрибут ("[{" -- і далі текст вузла),
    field.value дорівнював би "[{", JSON.parse падав би, catch тихо
    повертав [], редактор стартував би порожнім -- і "Зберегти" без жодної
    зміни стер би всі наявні сертифікати тренера з БД.

    Підпис навмисно містить лапки й апостроф -- саме ті символи, що ламають
    атрибут у подвійних лапках.
    """
    user = make_user()
    trainer = make_trainer(user, name='Лапковий Т.')
    trainer.certificates = [
        {'url': '/media/2026/06/a.webp', 'thumb': '/media/2026/06/a.webp',
         'caption': 'Диплом "Ін\'єкції"'},
        {'url': '/media/2026/06/b.webp', 'thumb': '/media/2026/06/b.webp',
         'caption': 'Просто підпис'},
    ]
    db.session.commit()
    login(client, user)

    resp = client.get('/trainer/certificates')
    assert resp.status_code == 200

    parser = _InputValueFinder('regalia-cert-field')
    parser.feed(resp.data.decode('utf-8'))
    assert parser.value is not None, 'поле #regalia-cert-field не знайдено в HTML'

    parsed = json.loads(parser.value)
    assert parsed == trainer.certificates


def test_own_media_bound_to_other_entity_is_not_rebound(client, media_root):
    """Власне медіа, вже привʼязане до ІНШОЇ сутності, у сертифікати не йде.

    Фото анкети тренер завантажує сам (uploader_id = він), тож перевірка
    «завантажив сам» його пропускала: підробивши POST із media_id фото,
    тренер отримував переприв'язку MediaFile до сертифікатів і
    перейменування файлу. Для адміна з карткою тренера так само досяжні
    обкладинки курсів і блогу, які він колись завантажив.
    """
    from werkzeug.datastructures import FileStorage

    from app.services import media_service
    from app.services.trainer_cabinet import get_or_create_profile

    user = make_user()
    trainer = make_trainer(user, name='Фото анкети Т.')
    profile = get_or_create_profile(trainer)
    db.session.commit()
    media, error = media_service.create_from_upload(
        FileStorage(stream=_png(), filename='photo.png', content_type='image/png'),
        entity_type='trainer_profile', entity_id=profile.id,
        usage_type='photo', uploader_id=user.id,
    )
    assert error is None
    db.session.commit()
    before = (media.entity_type, media.entity_id, media.usage_type, media.file_path)

    login(client, user)
    client.post('/trainer/certificates', data={'certificates': json.dumps([{
        'url': media.url, 'thumb': media.url, 'media_id': media.id,
        'caption': 'Підроблена позиція',
    }])}, follow_redirects=True)

    db.session.refresh(media)
    assert (media.entity_type, media.entity_id, media.usage_type,
            media.file_path) == before
    db.session.refresh(trainer)
    assert not any((c or {}).get('media_id') == media.id
                   for c in (trainer.certificates or []))


def test_complaints_are_rate_limited(client):
    """Кожна скарга -- лист кураторам; без ліміту одна вкладка засипала б їх."""
    user, _, cert = _trainer_with_certificate()
    login(client, user)
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate_complaint', return_value=[]):
        codes = [client.post(f'/trainer/certificates/{cert.id}/report',
                             data={'message': 'Помилка в ПІБ'}).status_code
                 for _ in range(6)]
    assert codes[:5] == [302] * 5
    assert codes[5] == 429


def test_uploads_are_rate_limited(client, media_root):
    """Завантаження кладе файл на диск ще до «Зберегти»: без ліміту тренер
    міг би безмежно засипати медіа-реєстр."""
    user = make_user()
    make_trainer(user, name='Завантажувач Т.')
    login(client, user)
    codes = [client.post('/trainer/certificates/upload',
                         data={'file': (_png(), 'a.png')},
                         content_type='multipart/form-data').status_code
             for _ in range(31)]
    assert all(c == 200 for c in codes[:30])
    assert codes[30] == 429


def test_downloads_are_rate_limited(client):
    """PDF рендериться на кожен клік -- повторні запити мають упертись у ліміт."""
    user, _, cert = _trainer_with_certificate()
    login(client, user)
    with patch('app.services.certificate_service.render_lecturer_pdf',
               return_value=b'%PDF-1.4 fake'):
        codes = [client.get(f'/trainer/certificates/{cert.id}/download').status_code
                 for _ in range(31)]
    assert all(c == 200 for c in codes[:30])
    assert codes[30] == 429


def test_save_warns_when_items_were_dropped(client):
    """Стара вкладка чи другий пристрій: частина позицій уже не тренерова.

    Раніше фільтр відкидав їх мовчки, і тренер бачив «Сертифікати
    збережено», хоча частини списку в базі вже не було.
    """
    user = make_user()
    trainer = make_trainer(user, name='Дві вкладки Т.')
    own = {'url': '/media/2026/06/own.webp', 'thumb': '/media/2026/06/own.webp',
           'caption': 'Моє'}
    trainer.certificates = [own]
    db.session.commit()
    login(client, user)
    client.post('/trainer/certificates', data={'certificates': json.dumps([
        own,
        {'url': '/media/2026/06/stale.webp', 'caption': 'З іншої вкладки'},
    ])})
    flashes = _flashes(client)
    assert 'Сертифікати збережено' not in flashes
    assert any('пропущено' in m and '(1)' in m for m in flashes)
    db.session.refresh(trainer)
    assert [c['url'] for c in trainer.certificates] == [own['url']]


def test_save_without_drops_reports_plain_success(client):
    user = make_user()
    trainer = make_trainer(user, name='Одна вкладка Т.')
    own = {'url': '/media/2026/06/own.webp', 'thumb': '/media/2026/06/own.webp',
           'caption': 'Моє'}
    trainer.certificates = [own]
    db.session.commit()
    login(client, user)
    client.post('/trainer/certificates', data={'certificates': json.dumps([own])})
    assert _flashes(client) == ['Сертифікати збережено']


@pytest.mark.parametrize('message', ['', '   '])
def test_empty_complaint_is_not_sent(client, message):
    """Порожня скарга не дає куратору жодної зачіпки, що виправляти."""
    user, _, cert = _trainer_with_certificate()
    login(client, user)
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate_complaint') as notify:
        resp = client.post(f'/trainer/certificates/{cert.id}/report',
                           data={'message': message})
    assert resp.status_code == 302
    assert not notify.called
    assert any(m.startswith('Опишіть') for m in _flashes(client))
