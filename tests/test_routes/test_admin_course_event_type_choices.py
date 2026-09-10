"""Вибір типу в адмінці курсу: активні + чинний, навіть застарілий.

Головна регресія тут -- курс зі старим типом («Курс», «Вебінар»).
Якщо його значення не потрапляє в choices, WTForms валить сабміт із
"Not a valid choice", і адміністратор не збереже навіть правку
заголовка, що типу взагалі не стосується.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.user import User
from tests.support.rbac import grant_role


@pytest.fixture
def admin():
    u = User.create_with_password(
        f'ch-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _course(event_type):
    course = Course(title='Курс', slug=f'ch-{uuid4().hex[:6]}',
                    is_active=True, event_type=event_type)
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, event_type=None):
    instance = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        price=100, event_type=event_type,
        start_date=datetime.now(timezone.utc) + timedelta(days=800),
    )
    db.session.add(instance)
    db.session.flush()
    return instance


def test_new_course_form_offers_only_active_types(client, admin):
    _login(client, admin)
    html = client.get('/admin/courses/new').get_data(as_text=True)
    assert 'value="scientific_conference"' in html
    assert 'value="professional_school"' in html
    assert 'value="webinar"' not in html, 'застарілий тип не пропонується'


def test_edit_form_keeps_deactivated_current_type(client, admin):
    _login(client, admin)
    course = _course('course')
    html = client.get(f'/admin/courses/{course.id}/edit').get_data(as_text=True)
    assert 'value="course"' in html
    assert 'застарілий' in html


def test_saving_course_with_deactivated_type_succeeds(client, admin):
    """Правка заголовка не мусить впиратись у застарілий тип."""
    _login(client, admin)
    course = _course('webinar')
    r = client.post(f'/admin/courses/{course.id}/edit', data={
        'title': 'Оновлений заголовок',
        'slug': course.slug,
        'event_type': 'webinar',
        'difficulty_level': '0',
        'base_price': '0',
    }, follow_redirects=True)

    assert r.status_code == 200
    db.session.expire(course)
    assert course.title == 'Оновлений заголовок'
    assert course.event_type == 'webinar'


def test_course_can_be_switched_to_new_bpr_type(client, admin):
    _login(client, admin)
    course = _course('course')
    client.post(f'/admin/courses/{course.id}/edit', data={
        'title': course.title,
        'slug': course.slug,
        'event_type': 'skills_training',
        'difficulty_level': '0',
        'base_price': '0',
    }, follow_redirects=True)

    db.session.expire(course)
    assert course.event_type == 'skills_training'


class TestInstanceEventTypeOverride:
    """Цикл збереження перевизначення виду заходу для проведення.

    Той самий патерн прямого виклику служби через test_request_context, що
    в tests/test_routes/test_instance_city.py::TestAdminPicker -- поле
    міста перевіряється так само, а повний HTTP POST на
    /admin/instances/<id>/edit довелось би обвішувати даними для полів,
    не повʼязаних із цим сценарієм (дата, курс, статус), що лише шумить.
    """

    def test_picked_override_is_stored_and_wins_over_course_type(self, app):
        from app.admin.forms import CourseInstanceForm
        from app.services import course_service

        course = _course('course')
        instance = _instance(course)
        db.session.commit()

        with app.test_request_context():
            form = CourseInstanceForm(obj=instance)
            form.event_type.data = 'skills_training'
            course_service.populate_instance_from_form(instance, form)

        assert instance.event_type == 'skills_training'
        assert instance.effective_event_type == 'skills_training'

    def test_empty_choice_is_saved_as_null_and_falls_back_to_course_type(self, app):
        """Порожній вибір («Як у курсу») лягає в колонку саме NULL, не ''."""
        from app.admin.forms import CourseInstanceForm
        from app.services import course_service

        course = _course('course')
        instance = _instance(course, event_type='skills_training')
        db.session.commit()

        with app.test_request_context():
            form = CourseInstanceForm(obj=instance)
            form.event_type.data = ''
            course_service.populate_instance_from_form(instance, form)

        assert instance.event_type is None
        assert instance.effective_event_type == 'course'


class TestInheritedTypeIsVisible:
    """Порожній варіант мусить називати той тип, який успадковується.

    Без назви в дужках «– Як у курсу –» нічого не повідомляє: щоб дізнатись,
    тренінг це чи фахова школа, менеджер мусив відкрити картку курсу в
    сусідній вкладці. Саме тому це поле й заводили -- бачити фактичний вид
    конкретної дати.
    """

    def test_edit_form_names_the_inherited_type(self, client, admin):
        _login(client, admin)
        course = _course('training')
        instance = _instance(course)
        db.session.commit()

        html = client.get(
            f'/admin/instances/{instance.id}/edit').get_data(as_text=True)

        assert 'Як у курсу (Тренінг)' in html

    def test_new_form_keeps_bare_label_while_course_is_unknown(self, client, admin):
        """На /new курс ще не обрано -- називати нічого."""
        _login(client, admin)

        html = client.get('/admin/instances/new').get_data(as_text=True)

        assert 'Як у курсу' in html
        assert 'Як у курсу (' not in html

    def test_new_form_names_the_type_of_a_preselected_course(self, client, admin):
        """/instances/new?course_id=X -- курс уже відомий, тип називаємо."""
        _login(client, admin)
        course = _course('training')
        db.session.commit()

        html = client.get(
            f'/admin/instances/new?course_id={course.id}').get_data(as_text=True)

        assert 'Як у курсу (Тренінг)' in html

    def test_course_without_type_keeps_bare_label(self, client, admin):
        _login(client, admin)
        course = _course(None)
        instance = _instance(course)
        db.session.commit()

        html = client.get(
            f'/admin/instances/{instance.id}/edit').get_data(as_text=True)

        assert 'Як у курсу' in html
        assert 'Як у курсу (' not in html


class TestInstancesListShowsType:
    """Реєстр проведень мусить називати фактичний вид кожної дати."""

    def test_list_shows_effective_type_of_each_instance(self, client, admin):
        _login(client, admin)
        course = _course('seminar')
        _instance(course, event_type='training')
        db.session.commit()

        html = client.get('/admin/instances').get_data(as_text=True)

        assert 'Тренінг' in html

    def test_list_shows_inherited_type_when_not_overridden(self, client, admin):
        _login(client, admin)
        course = _course('professional_school')
        _instance(course)
        db.session.commit()

        html = client.get('/admin/instances').get_data(as_text=True)

        assert 'Фахова (тематична) школа' in html


    def test_override_marker_carries_a_readable_label(self, client, admin):
        """Зірочка не мусить бути єдиним носієм змісту."""
        _login(client, admin)
        course = _course('seminar')
        _instance(course, event_type='training')
        db.session.commit()

        html = client.get('/admin/instances').get_data(as_text=True)

        assert 'visually-hidden">(перевизначено для цієї дати)' in html
        assert 'aria-hidden="true">*' in html
