"""Розділ сертифікатів у кабінеті тренера."""
import io
import json
import tempfile
from html.parser import HTMLParser
from itertools import count

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
    from unittest.mock import patch

    user, _, cert = _trainer_with_certificate()
    login(client, user)
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate_complaint') as notify:
        resp = client.post(f'/trainer/certificates/{cert.id}/report',
                           data={'message': 'Помилка в ПІБ'},
                           follow_redirects=True)
    assert resp.status_code == 200
    assert notify.called


def test_report_error_on_foreign_certificate_is_404(client):
    _, _, foreign = _trainer_with_certificate()
    other_user = make_user()
    make_trainer(other_user, name='Чужий Т. 3')
    login(client, other_user)
    resp = client.post(f'/trainer/certificates/{foreign.id}/report',
                       data={'message': 'X'})
    assert resp.status_code == 404


# --- власні сертифікати (редагування тренером) --------------------------


def test_trainer_saves_own_regalia(client):
    user = make_user()
    trainer = make_trainer(user, name='Регалійний Т.')
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
