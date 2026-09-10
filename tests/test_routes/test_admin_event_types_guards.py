"""Запобіжники довідника видів заходів.

Кожен тест тут стереже поведінку, якої бракувало первісній реалізації і
яка ламається тихо: зіпсована граматика сертифіката, непрохідна форма
курсу, мовчазно проковтнутий ввід.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.event_type import EventType
from app.models.user import User
from app.services import event_types
from tests.support.rbac import grant_role


@pytest.fixture
def admin():
    u = User.create_with_password(
        f'etg-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _custom(**kw):
    row = EventType(code=kw.pop('code', f'z-{uuid4().hex[:6]}'),
                    name=kw.pop('name', 'Тимчасовий тип'),
                    sort_order=kw.pop('sort_order', 500), **kw)
    db.session.add(row)
    db.session.flush()
    event_types.reset_cache()
    return row


def _form_for(rows, **overrides):
    """Повний сабміт таблиці: усі рядки з чинними значеннями."""
    data = {}
    for row in rows:
        data[f'name__{row.id}'] = row.name
        data[f'accusative__{row.id}'] = row.name_accusative or ''
        data[f'genitive__{row.id}'] = row.name_genitive or ''
        data[f'sort__{row.id}'] = str(row.sort_order)
        if row.is_active:
            data[f'active__{row.id}'] = 'on'
    data.update(overrides)
    return data


# --- відмінки -----------------------------------------------------------

def test_add_requires_both_cases(client, admin):
    """Тип без відмінків друкує в сертифікаті називний -- це той самий
    дефект, заради якого довідник і робився."""
    _login(client, admin)
    code = f'z-{uuid4().hex[:6]}'
    before = EventType.query.count()

    r = client.post('/admin/event-types/add', data={
        'code': code, 'name': 'Воркшоп', 'accusative': 'воркшоп',
    }, follow_redirects=True)

    assert r.status_code == 200
    assert EventType.query.count() == before, 'тип без родового не мав додатись'
    assert EventType.query.filter_by(code=code).first() is None


def test_add_succeeds_with_both_cases(client, admin):
    _login(client, admin)
    code = f'z-{uuid4().hex[:6]}'

    client.post('/admin/event-types/add', data={
        'code': code, 'name': 'Воркшоп',
        'accusative': 'воркшоп', 'genitive': 'воркшопу',
    }, follow_redirects=True)

    row = EventType.query.filter_by(code=code).first()
    assert row is not None
    assert (row.name_accusative, row.name_genitive) == ('воркшоп', 'воркшопу')
    db.session.delete(row)
    db.session.commit()
    event_types.reset_cache()


def test_list_flags_rows_without_cases(client, admin):
    _login(client, admin)
    row = _custom(name='Без відмінків', name_accusative=None, name_genitive=None)
    db.session.commit()

    html = client.get('/admin/event-types').get_data(as_text=True)

    assert 'без відмінків' in html
    assert 'Без відмінків' in html
    db.session.delete(row)
    db.session.commit()
    event_types.reset_cache()


# --- активність ---------------------------------------------------------

def test_cannot_deactivate_every_type(client, admin):
    """Порожній перелік активних робить форму курсу непрохідною, і вийти
    з цього через інтерфейс уже не можна."""
    _login(client, admin)
    rows = EventType.query.all()
    data = _form_for(rows)
    for row in rows:
        data.pop(f'active__{row.id}', None)

    client.post('/admin/event-types/save', data=data, follow_redirects=True)

    db.session.expire_all()
    event_types.reset_cache()
    assert EventType.query.filter_by(is_active=True).count() > 0
    assert event_types.choices(), 'форма курсу лишилась би без варіантів'


def test_deactivating_one_type_still_works(client, admin):
    _login(client, admin)
    row = _custom(is_active=True, name_accusative='тимчасовий',
                  name_genitive='тимчасового')
    db.session.commit()
    rows = EventType.query.all()
    data = _form_for(rows)
    data.pop(f'active__{row.id}')

    client.post('/admin/event-types/save', data=data, follow_redirects=True)

    db.session.expire_all()
    assert db.session.get(EventType, row.id).is_active is False
    db.session.delete(db.session.get(EventType, row.id))
    db.session.commit()
    event_types.reset_cache()


# --- валідація вводу ----------------------------------------------------

def test_save_rejects_overlong_name_and_keeps_old_value(client, admin):
    """Сабміт повз браузерний maxlength інакше дав би DataError на весь
    сабміт і загальне «Помилка при збереженні»."""
    _login(client, admin)
    row = _custom(name='Коротка назва', name_accusative='коротку',
                  name_genitive='короткої')
    db.session.commit()
    rows = EventType.query.all()
    data = _form_for(rows, **{f'name__{row.id}': 'я' * 200})

    r = client.post('/admin/event-types/save', data=data, follow_redirects=True)

    assert 'довша за 120' in r.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(EventType, row.id).name == 'Коротка назва'
    db.session.delete(db.session.get(EventType, row.id))
    db.session.commit()
    event_types.reset_cache()


def test_save_reports_non_numeric_sort_instead_of_swallowing_it(client, admin):
    _login(client, admin)
    row = _custom(sort_order=500, name_accusative='а', name_genitive='б')
    db.session.commit()
    rows = EventType.query.all()
    data = _form_for(rows, **{f'sort__{row.id}': 'перший'})

    r = client.post('/admin/event-types/save', data=data, follow_redirects=True)

    assert 'не число' in r.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(EventType, row.id).sort_order == 500
    db.session.delete(db.session.get(EventType, row.id))
    db.session.commit()
    event_types.reset_cache()


def test_add_rejects_code_longer_than_thirty(client, admin):
    _login(client, admin)
    before = EventType.query.count()

    client.post('/admin/event-types/add', data={
        'code': 'a' * 31, 'name': 'Довгий', 'accusative': 'д', 'genitive': 'д',
    }, follow_redirects=True)

    assert EventType.query.count() == before


# --- переставляння ------------------------------------------------------

def test_move_down_swaps_with_neighbour(client, admin):
    _login(client, admin)
    ordered = EventType.query.order_by(
        EventType.sort_order, EventType.name).all()
    first, second = ordered[0], ordered[1]

    client.post(f'/admin/event-types/{first.id}/move',
                data={'direction': 'down'}, follow_redirects=True)

    db.session.expire_all()
    event_types.reset_cache()
    after = EventType.query.order_by(EventType.sort_order, EventType.name).all()
    assert [r.id for r in after[:2]] == [second.id, first.id]


def test_move_up_on_first_row_is_a_noop(client, admin):
    _login(client, admin)
    ordered = EventType.query.order_by(
        EventType.sort_order, EventType.name).all()
    before = [r.id for r in ordered]

    client.post(f'/admin/event-types/{ordered[0].id}/move',
                data={'direction': 'up'}, follow_redirects=True)

    db.session.expire_all()
    event_types.reset_cache()
    after = EventType.query.order_by(EventType.sort_order, EventType.name).all()
    assert [r.id for r in after] == before


# --- перелік курсів у рядку --------------------------------------------

def test_row_lists_courses_using_the_type(client, admin):
    _login(client, admin)
    course = Course(title='Курс на видному місці', slug=f'et-{uuid4().hex[:6]}',
                    is_active=True, event_type='seminar')
    db.session.add(course)
    db.session.commit()

    html = client.get('/admin/event-types').get_data(as_text=True)

    assert 'Курс на видному місці' in html
    assert 'event_type=seminar' in html, 'лічильник має вести на фільтр'
    db.session.delete(course)
    db.session.commit()

# --- лічильник вживання -------------------------------------------------

def test_usage_counts_courses_by_code(client, admin):
    """Лічильник переїхав зі служби назв у роут адмінки разом із запитом."""
    from app.admin.routes_event_types import _usage

    course = Course(title='Симпозіумний курс', slug=f'u-{uuid4().hex[:6]}',
                    event_type='symposium')
    db.session.add(course)
    db.session.flush()

    assert _usage().get('symposium', 0) >= 1

    db.session.delete(course)
    db.session.commit()
