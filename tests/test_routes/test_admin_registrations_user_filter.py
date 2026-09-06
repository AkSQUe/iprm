"""Фільтр `user_id` у реєстрі реєстрацій і посилання з картки користувача.

Реєстр реєстрацій за замовчуванням показує лише майбутні заходи
(`scope='upcoming'`, `routes_registrations.py:476`). Посилання з картки
користувача мусить нейтралізувати цей дефолт через `scope=all` -- інакше
минулі реєстрації людини зникають з результату.
"""
from tests.support.rbac import grant_role
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'ruf-{_uid()}@test.com', 'password123',
        first_name='R', last_name='F', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _make_registration(course_title, phone):
    """Користувач + курс + минулий інстанс + реєстрація -- одним набором.

    Минула дата навмисна: без неї тест не відрізнив би `scope=all` від
    дефолтного `upcoming`, а саме це і є суттю фільтра.
    """
    user = User.create_with_password(
        f'ruf-{_uid()}@test.com', 'password123', first_name='П', last_name='Т',
    )
    db.session.flush()
    course = Course(title=course_title, slug=f'ruf-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone=phone,
        specialty='T', workplace='Клініка', status='pending', payment_status='unpaid',
    )
    db.session.add(reg)
    db.session.commit()
    return user, course, inst, reg


def _cleanup(user, course, inst, reg):
    db.session.delete(db.session.merge(reg))
    db.session.delete(db.session.merge(inst))
    db.session.delete(db.session.merge(course))
    db.session.delete(db.session.merge(user))
    db.session.commit()


def _instance_href(inst_id):
    """Посилання на рядок цього заходу -- унікальне, на відміну від назви
    курсу, яка також світиться в опціях `<select>` фільтра курсу."""
    return f'/admin/instances/{inst_id}/registrations'


def _tbody(html):
    """Вміст `<tbody>` без прихованого поля `next` рядкових форм.

    `next` завжди відбиває сирий query-string запиту (щоб дія в рядку
    повернула туди, звідки прийшли) -- саме тому порожній `user_id=` у
    рядку запиту й так лишав би слід там, не зачіпаючи жодного фільтра чи
    рядка списку. Це відомий і бажаний ефект, не регресія, тож із
    порівняння його прибираємо.
    """
    match = re.search(r'<tbody>.*?</tbody>', html, re.S)
    assert match, 'у відповіді немає <tbody> списку реєстрацій'
    body = match.group(0)
    return re.sub(r'<input type="hidden" name="next"[^>]*>', '', body)


def test_user_id_narrows_to_that_users_registrations(client, admin):
    """`user_id` + `scope=all` показує рівно реєстрацію цього користувача.

    Назву курсу як маркер не беремо: вона світиться і в опціях `<select>`
    фільтра курсу незалежно від того, які рядки відфільтровано.
    """
    user_a, course_a, inst_a, reg_a = _make_registration(
        f'Курс А {_uid()}', '+380671110001')
    user_b, course_b, inst_b, reg_b = _make_registration(
        f'Курс Б {_uid()}', '+380671110002')
    _login(client, admin)
    try:
        html = client.get(
            f'/admin/registrations?user_id={user_a.id}&scope=all',
        ).get_data(as_text=True)
        assert _instance_href(inst_a.id) in html
        assert _instance_href(inst_b.id) not in html
    finally:
        _cleanup(user_a, course_a, inst_a, reg_a)
        _cleanup(user_b, course_b, inst_b, reg_b)


def test_request_without_user_id_is_unchanged(client, admin):
    """Без `user_id` список -- байт-у-байт той самий, що й до фільтра.

    Порівнюємо саме `<tbody>`: сторінка вшиває поточний query-string у
    self-посилання (og:url тощо), тож повна відповідь відрізнялась би вже
    самим порожнім `user_id=` у рядку запиту, хоч список і не змінився б.
    """
    user, course, inst, reg = _make_registration(f'Курс В {_uid()}', '+380671110003')
    _login(client, admin)
    try:
        # Реєстрація минула (scope=all нейтралізує upcoming-дефолт), тож
        # для порівняння двох відповідей саме сирого списку достатньо.
        without_filter = client.get('/admin/registrations?scope=all').get_data(as_text=True)
        with_empty_user_id = client.get(
            '/admin/registrations?scope=all&user_id=',
        ).get_data(as_text=True)
        assert _tbody(without_filter) == _tbody(with_empty_user_id)
        assert _instance_href(inst.id) in without_filter
    finally:
        _cleanup(user, course, inst, reg)


def test_absurdly_large_user_id_returns_200_not_500(client, admin):
    """`user_id` за межами BIGINT -- те саме сміття, що й нечислове значення.

    `int_arg` віддає його психопг2 як є: Python int без стелі, а колонка
    в БД -- BIGINT. Без клампу в `_listing.int_arg` це падало б у драйвері
    з `OverflowError` -> 500 замість чесного "нічого не знайдено".
    """
    _login(client, admin)
    resp = client.get('/admin/registrations?user_id=99999999999999999999&scope=all')
    assert resp.status_code == 200
    # Той самий int_arg читає й instance_id -- де баг і був знайдений вперше.
    resp2 = client.get('/admin/registrations?instance_id=99999999999999999999&scope=all')
    assert resp2.status_code == 200


def test_course_id_outside_options_still_shows_chip_value(client, admin):
    """Курс, якого нема серед опцій `<select>` -- чіпс усе одно показує
    значення, а не порожній `Курс:` без підпису.

    `course_id` валідує `int_arg` (будь-яке позитивне число в межах BIGINT),
    а опції `<select>` у filter_bar -- лише живий список курсів на момент
    рендеру. Розбіжність між тим, що приймає фільтр, і тим, що показує
    `<select>`, тут природна (взятий навмання id, або курс видалили після
    того, як на нього хтось уже перейшов), а не ознака зламаного запиту.
    """
    missing_course_id = 9_000_000_000
    _login(client, admin)
    html = client.get(
        f'/admin/registrations?scope=all&course_id={missing_course_id}',
    ).get_data(as_text=True)
    assert re.search(
        rf'<span class="admin-chip__key">Курс:</span>\s*{missing_course_id}', html,
    )


def test_filter_bar_export_carries_user_id(client, admin):
    """Кнопка «Експорт XLSX» несе `user_id`, хоч у панелі й нема окремого
    поля під нього.

    `user_id` -- не декларований `fields`-параметр панелі, тож без явного
    `base_args` посилання експорту будувалось би БЕЗ нього -- і файл
    вивантажив би весь реєстр замість зрізу по цій людині.
    """
    _login(client, admin)
    html = client.get(
        f'/admin/registrations?user_id={admin.id}&scope=all',
    ).get_data(as_text=True)
    export_href = f'/admin/registrations/export?scope=all&amp;user_id={admin.id}'
    assert re.search(rf'<a href="{re.escape(export_href)}"', html), html


def test_filter_bar_form_keeps_user_id_as_hidden_field(client, admin):
    """«Застосувати» -- GET-форма: значення, яких нема серед видимих полів,
    переживають сабміт лише як приховані інпути з `base_args`.

    Без `user_id` у `base_args` цього прихованого поля не було б -- і клік
    «Застосувати» тихо повертав би менеджера на невідфільтрований реєстр.
    """
    _login(client, admin)
    html = client.get(
        f'/admin/registrations?user_id={admin.id}&scope=all',
    ).get_data(as_text=True)
    assert f'<input type="hidden" name="user_id" value="{admin.id}">' in html


def test_filter_bar_reset_keeps_user_id_alongside_active_filter(client, admin):
    """«Скинути все» знімає лише звичайні фільтри -- `user_id` (як і scope)
    переживає скидання, бо це контекст переходу з картки користувача, а не
    поле, яке можна зняти з панелі.

    Чіпси й «Скинути все» рендеряться лише коли є активний `fields`-фільтр
    (`_filter_bar.html`: `{% if ns.count or has_search %}`), тож для самої
    появи блока додаємо ще й `status`.
    """
    _login(client, admin)
    html = client.get(
        f'/admin/registrations?user_id={admin.id}&scope=all&status=pending',
    ).get_data(as_text=True)
    reset_href = f'/admin/registrations?scope=all&amp;user_id={admin.id}'
    assert re.search(
        rf'<a class="admin-filters__reset" href="{re.escape(reset_href)}"', html,
    ), html


def test_card_heading_links_with_user_id_and_scope_all(client, admin):
    """Посилання «Відкрити в реєстрі» несе обидва параметри й стилізоване
    як кнопка (btn-admin), а не як текст, зварений у заголовок секції.

    Перевіряємо саме тег навколо тексту посилання, а не просте входження
    підрядка -- інакше тест пройшов би й на нерозгорнутому шаблоні.
    """
    _login(client, admin)
    html = client.get(f'/admin/users/{admin.id}').get_data(as_text=True)
    href = f'/admin/registrations?user_id={admin.id}&amp;scope=all'
    pattern = (
        rf'<a href="{re.escape(href)}"\s+'
        rf'class="btn-admin btn-admin--secondary btn-admin--sm">\s*'
        rf'Відкрити в реєстрі\s*</a>'
    )
    assert re.search(pattern, html), html
