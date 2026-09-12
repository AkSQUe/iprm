"""Адмінка довідника видів заходів: доступ, збереження, додавання, видалення."""
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
        f'et-{uuid4().hex[:6]}@test.com', 'password123',
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


def test_requires_admin(client):
    assert client.get('/admin/event-types').status_code in (302, 401, 403)


def test_list_shows_active_and_legacy_rows(client, admin):
    _login(client, admin)
    html = client.get('/admin/event-types').get_data(as_text=True)
    assert 'Наукова конференція' in html
    assert 'Фахова (тематична) школа' in html
    # Саме за кодом у комірці: рядок «Курс» є в хлібних крихтах («Курси»)
    # незалежно від таблиці, тож перевірка за назвою нічого не стерегла б.
    # Код друкується другим поверхом під назвою (.admin-mono), а не власною
    # колонкою: окрема колонка під нередаговане значення забирала 132px у
    # полів, які тут і редагують.
    assert 'admin-mono admin-text-muted">course<' in html,         'застарілий рядок теж мусить бути видимим'


def test_save_updates_names_cases_and_flags(client, admin):
    _login(client, admin)
    row = _custom(name='Стара назва', is_active=True)
    client.post('/admin/event-types/save', data={
        f'name__{row.id}': 'Нова назва',
        f'accusative__{row.id}': 'нову назву',
        f'genitive__{row.id}': 'нової назви',
        f'sort__{row.id}': '7',
        f'tr__en__{row.id}': 'New name',
    })
    db.session.expire(row)
    assert row.name == 'Нова назва'
    assert row.name_accusative == 'нову назву'
    assert row.name_genitive == 'нової назви'
    assert row.sort_order == 7
    assert row.t('name', 'en') == 'New name'
    assert row.is_active is False, 'галка не прийшла -- тип деактивовано'


def test_save_keeps_row_active_when_checkbox_present(client, admin):
    _login(client, admin)
    row = _custom(is_active=True)
    client.post('/admin/event-types/save', data={
        f'name__{row.id}': row.name,
        f'active__{row.id}': 'on',
    })
    db.session.expire(row)
    assert row.is_active is True


def test_save_ignores_blank_name(client, admin):
    _login(client, admin)
    row = _custom(name='Лишається')
    client.post('/admin/event-types/save', data={f'name__{row.id}': '   '})
    db.session.expire(row)
    assert row.name == 'Лишається'


def test_add_creates_row(client, admin):
    _login(client, admin)
    code = f'z-{uuid4().hex[:6]}'
    r = client.post('/admin/event-types/add', data={
        'code': code, 'name': 'Новий вид',
        'accusative': 'новий вид', 'genitive': 'нового виду',
    })
    assert r.status_code == 302
    row = EventType.query.filter_by(code=code).one()
    assert row.name == 'Новий вид'
    assert row.is_active is True


def test_add_rejects_duplicate_code(client, admin):
    _login(client, admin)
    before = EventType.query.count()
    client.post('/admin/event-types/add', data={'code': 'seminar', 'name': 'Дубль'})
    assert EventType.query.count() == before


def test_add_rejects_empty_code_or_name(client, admin):
    _login(client, admin)
    before = EventType.query.count()
    client.post('/admin/event-types/add', data={'code': '  ', 'name': 'Без коду'})
    client.post('/admin/event-types/add', data={'code': 'ok-code', 'name': '  '})
    assert EventType.query.count() == before


def test_add_rejects_code_with_spaces_or_cyrillic(client, admin):
    """Код іде далі в партнерський API і xlsx як є (нижній регістр, без
    пробілів). HTML-форма це підказує (maxlength, "латиницею"), але без
    серверної перевірки хибний код проходить і псує обидва контракти."""
    _login(client, admin)
    before = EventType.query.count()

    client.post('/admin/event-types/add', data={
        'code': 'не код', 'name': 'Погана назва',
    })
    assert EventType.query.count() == before, 'кирилиця в коді не мала пройти'

    client.post('/admin/event-types/add', data={
        'code': 'has space', 'name': 'Ще одна погана',
    })
    assert EventType.query.count() == before, 'пробіл у коді не мав пройти'


def test_delete_removes_unused_row(client, admin):
    _login(client, admin)
    row = _custom()
    code = row.code
    client.post(f'/admin/event-types/{row.id}/delete')
    assert EventType.query.filter_by(code=code).first() is None


def test_delete_is_blocked_for_row_in_use(client, admin):
    _login(client, admin)
    row = _custom()
    db.session.add(Course(title='К', slug=f'd-{uuid4().hex[:6]}', event_type=row.code))
    db.session.flush()

    client.post(f'/admin/event-types/{row.id}/delete')
    assert EventType.query.filter_by(code=row.code).first() is not None, (
        'вживаний тип видаляти не можна -- його деактивують'
    )
