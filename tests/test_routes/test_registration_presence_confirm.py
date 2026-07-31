"""Підтвердження очної участі на формі реєстрації.

На ГІБРИДНОМУ проведенні частина тарифів онлайнові, частина очні. Раніше
блок "я точно приїду" показувався всім, бо гейт стояв на форматі заходу, а
тариф проведення взагалі не знав свого формату -- він губився при
копіюванні з шаблону курсу.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_tariff import CourseTariff
from app.models.instance_tariff import InstanceTariff
from app.services import course_service


def _instance(event_format, location='Київ'):
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=f'pc-{uuid4().hex[:6]}',
                    is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format=event_format,
        location=location,
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(inst)
    db.session.commit()
    return inst


def _tariff(inst, name, event_format, price=1000):
    t = InstanceTariff(instance_id=inst.id, name=name, price=price,
                       event_format=event_format, sort_order=0, is_active=True)
    db.session.add(t)
    db.session.commit()
    return t


@pytest.fixture
def logged_in(client):
    """Сторінка реєстрації доступна лише авторизованому користувачу."""
    from app.models.user import User
    user = User.create_with_password(
        f'u-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True)
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
    return user


def _page(client, inst):
    resp = client.get(f'/registration/instance/{inst.id}/register')
    assert resp.status_code == 200, f'очікували форму, отримали {resp.status_code}'
    return resp.get_data(as_text=True)


# --- модель -----------------------------------------------------------------

@pytest.mark.parametrize('fmt, expected', [
    ('online', False),
    ('offline', True),
    (None, True),          # не вказано -> вважаємо очною
])
def test_requires_presence(fmt, expected):
    assert InstanceTariff(name='X', price=0, event_format=fmt).requires_presence \
        is expected


# --- копіювання з шаблону курсу ---------------------------------------------

def test_format_is_copied_from_course_template(client):
    """Саме тут формат і губився: копія тарифу не знала, очна це участь."""
    inst = _instance('hybrid')
    db.session.add_all([
        CourseTariff(course_id=inst.course_id, name='Онлайн', price=1000,
                     event_format='online', sort_order=0, is_active=True),
        CourseTariff(course_id=inst.course_id, name='Практикум', price=6000,
                     event_format='offline', sort_order=1, is_active=True),
    ])
    db.session.commit()

    assert course_service.copy_course_tariffs_to_instance(inst, replace=True) == 2
    db.session.commit()

    by_name = {t.name: t for t in inst.tariffs}
    assert by_name['Онлайн'].event_format == 'online'
    assert by_name['Практикум'].event_format == 'offline'
    assert by_name['Онлайн'].requires_presence is False
    assert by_name['Практикум'].requires_presence is True


# --- форма реєстрації -------------------------------------------------------

def test_offline_event_always_requires_confirmation(client, logged_in):
    inst = _instance('offline')
    _tariff(inst, 'Практикум', 'offline', 6000)
    html = _page(client, inst)

    assert 'confirm_offline' in html
    assert 'data-presence-confirm' not in html   # без JS-перемикання
    assert 'required' in html.split('id="confirm_offline"')[1][:200]


def test_online_event_has_no_confirmation(client, logged_in):
    inst = _instance('online', location=None)
    _tariff(inst, 'Онлайн', 'online', 1000)
    assert 'confirm_offline' not in _page(client, inst)


def test_hybrid_block_is_hidden_and_optional_until_js(client, logged_in):
    """Прихована, але обов'язкова галочка не дала б відправити форму --
    браузер каже лише "not focusable". Тож required теж знято."""
    inst = _instance('hybrid')
    _tariff(inst, 'Онлайн', 'online', 1000)
    html = _page(client, inst)

    assert 'data-presence-confirm' in html
    assert 'hidden' in html.split('data-presence-confirm')[1][:40]
    checkbox = html.split('id="confirm_offline"')[1][:200]
    assert 'required' not in checkbox


def test_hybrid_tariffs_carry_presence_flag(client, logged_in):
    inst = _instance('hybrid')
    online = _tariff(inst, 'Онлайн', 'online', 1000)
    practice = _tariff(inst, 'Практикум', 'offline', 6000)
    html = _page(client, inst)

    for tariff, expected in ((online, '0'), (practice, '1')):
        radio = html.split(f'value="{tariff.id}"')[1][:220]
        assert f'data-presence="{expected}"' in radio


def test_tariff_without_format_counts_as_presence(client, logged_in):
    """Тарифи, створені до появи поля, лишаються з NULL -- поведінка
    не змінюється, попередження показується."""
    inst = _instance('hybrid')
    tariff = _tariff(inst, 'Старий тариф', None, 3000)
    radio = _page(client, inst).split(f'value="{tariff.id}"')[1][:220]
    assert 'data-presence="1"' in radio


def test_hybrid_city_banner_follows_tariff(client, logged_in):
    """Банер угорі казав "захід проходить ОФЛАЙН" навіть онлайн-учаснику --
    просто під бейджем "+ онлайн". Тепер він у тій самій зв'язці, що й
    галочки."""
    inst = _instance('hybrid')
    _tariff(inst, 'Онлайн', 'online', 1000)
    html = _page(client, inst)

    assert html.count('data-presence-confirm') == 2   # банер + галочки
    banner = html.split('reg-location-callout')[1][:200]
    assert 'hidden' in banner
def test_admin_can_set_tariff_format(client):
    """Формат редагується в адмінці -- інакше наявні тарифи не полагодити."""
    from app.models.user import User
    admin = User.create_with_password(
        f'a-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True)
    db.session.commit()
    with client.session_transaction() as s:
        s['_user_id'] = str(admin.id)

    inst = _instance('hybrid')
    tariff = _tariff(inst, 'Онлайн', None, 1000)
    r = client.post(f'/admin/tariffs/{tariff.id}/edit', data={
        'name': 'Онлайн', 'price': '1000', 'sort_order': '0',
        'description': '', 'event_format': 'online', 'is_active': 'y',
    })
    assert r.status_code == 302
    assert db.session.get(InstanceTariff, tariff.id).event_format == 'online'
