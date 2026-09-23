"""Мова й доступність публічних сторінок кабінету тренера.

Кабінет перекладений (uk/ru/en), тож контент моделей іде через .t(), а
не сирими колонками, і тексти помилок -- через _(), а не українські рядки
сервісу. Сторінку дашборда перевіряємо ще й на порядок каскаду: лічильники
живуть у .iprm-stat-grid, чий `.apple-page .iprm-stat-grid` (0,2,0) інакше
перебиває сторінкову сітку (0,1,0).
"""
import io
import pathlib
import re
from uuid import uuid4

from app.extensions import db
from app.models.city import City
from app.services.trainer_links import set_trainers
from tests.test_trainer_cabinet._factories import (
    login, make_course, make_instance, make_trainer, make_user,
)

STATIC = pathlib.Path(__file__).resolve().parents[2] / 'app' / 'static'


def test_dashboard_uses_translated_content(client):
    user = make_user()
    trainer = make_trainer(user, name='Іваненко Іван')
    trainer.set_translation('en', 'full_name', 'Ivan Ivanenko')
    course = make_course('Кислотно-основний стан')
    course.set_translation('en', 'title', 'Acid-base balance')
    city = City(name=f'Місто {uuid4().hex[:6]}')
    city.set_translation('en', 'name', 'Test City EN')
    db.session.add(city)
    db.session.commit()
    set_trainers(course, [trainer.id])
    db.session.commit()
    inst = make_instance(course)
    inst.city_id = city.id
    db.session.commit()
    login(client, user)
    html = client.get('/en/trainer/').get_data(as_text=True)
    # Останнє слово імені в h1 -- градієнтний span, тож ім'я розірване тегом.
    assert 'Ivan <span class="apple-gradient-text">Ivanenko</span>' in html
    assert 'Іваненко' not in html
    assert 'Test City EN' in html
    # Назва і в заході, і в "Мої курси" -- обидві перекладені.
    assert html.count('Acid-base balance') == 2
    assert 'Кислотно-основний стан' not in html


def test_photo_error_is_translated(client):
    user = make_user()
    make_trainer(user)
    login(client, user)
    resp = client.post('/en/trainer/profile', data={
        'photo': (io.BytesIO(b'not an image'), 'photo.png'),
    }, content_type='multipart/form-data')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and 'form-error' in html
    # Український рядок media_service не має діставатись en-сторінки.
    assert 'Не вдалося прочитати зображення' not in html
    assert 'Could not process the photo' in html


def test_theses_textarea_carries_item_label(client):
    user = make_user()
    make_trainer(user)
    login(client, user)
    html = client.get('/en/trainer/proposals/new').get_data(as_text=True)
    assert 'data-item-label="Point"' in html


def test_theses_script_names_inputs():
    js = (STATIC / 'js' / 'trainer-theses.js').read_text(encoding='utf-8')
    assert 'data-item-label' in js and "setAttribute('aria-label'" in js


def test_counts_grid_outranks_stat_grid():
    css = (STATIC / 'css' / 'page-trainer-home.css').read_text(encoding='utf-8')
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    selectors = re.findall(r'([^{}]*\.trainer-events__counts)\s*\{', css)
    assert selectors, 'правило для лічильників зникло'
    for selector in selectors:
        assert selector.strip().startswith('.apple-page '), selector


def test_certificates_page_is_translated(client):
    """Розділ сертифікатів кабінету -- перекладений, як і решта кабінету."""
    user = make_user()
    make_trainer(user, name='Сертифікати EN')
    login(client, user)
    html = client.get('/en/trainer/certificates').get_data(as_text=True)
    assert 'Your own certificates' in html
    assert 'For the events you conducted' in html
    assert 'Власні сертифікати' not in html
    assert 'За проведені заходи' not in html


def test_certificate_upload_error_is_translated(client):
    """Текст відмови media_service -- український і без _(): тренеру
    показуємо перекладене загальне повідомлення, причина лишається в лозі."""
    user = make_user()
    make_trainer(user, name='Завантаження EN')
    login(client, user)
    resp = client.post('/en/trainer/certificates/upload',
                       data={'file': (io.BytesIO(b'not an image'), 'bad.png')},
                       content_type='multipart/form-data')
    assert resp.status_code == 400
    error = resp.get_json()['error']
    assert error.startswith('Could not process the file')
    assert not re.search('[А-Яа-яІіЇїЄєҐґ]', error)
