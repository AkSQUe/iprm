"""Тема проведення в адмінці: поле форми, збереження, підпис картки."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.user import User
from tests.support.rbac import grant_role


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin_client(app, client):
    user = User.create_with_password(
        f'topic-admin-{_uid()}@test.com', 'Passw0rd!123',
        first_name='Адмін', email_confirmed=True,
    )
    user.is_active = True
    grant_role(user, 'super_admin')
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    yield client
    # Прибираємо за собою -- зайві користувачі зсувають сторінки сусідніх
    # тестів (див. tests/test_routes/test_api_v1_clients.py).
    db.session.delete(user)
    db.session.commit()


@pytest.fixture
def instance(app):
    course = Course(title='Базовий курс', slug=f'tp-{_uid()}',
                    short_description='d', is_active=True, base_price=100)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _filled_form(app, instance, topic):
    from app.admin.forms import CourseInstanceForm
    from app.admin.routes_instances import _populate_choices
    from app.services import course_service

    with app.test_request_context():
        form = CourseInstanceForm(obj=instance)
        _populate_choices(form, instance=instance)
        form.topic.data = topic
        course_service.populate_instance_from_form(instance, form)
    return instance


class TestForm:
    def test_topic_is_optional(self, app, instance):
        from app.admin.forms import CourseInstanceForm

        with app.test_request_context():
            form = CourseInstanceForm(obj=instance)
        assert form.topic.label.text == 'Тема'
        assert not form.topic.flags.required

    def test_typed_topic_is_stored(self, app, instance):
        _filled_form(app, instance, 'PRP у практиці ортопеда')
        assert instance.topic == 'PRP у практиці ортопеда'
        assert instance.effective_title == 'PRP у практиці ортопеда'

    def test_cleared_topic_becomes_null_not_empty_string(self, app, instance):
        """Порожнє поле мусить лягти NULL, інакше колонка накопичує сміття."""
        instance.topic = 'Стара тема'
        _filled_form(app, instance, '   ')
        assert instance.topic is None
        assert instance.effective_title == 'Базовий курс'

    def test_topic_does_not_touch_course_title(self, app, instance):
        _filled_form(app, instance, 'Окрема тема')
        assert instance.course.title == 'Базовий курс'


class TestCard:
    def test_edit_page_offers_topic_field(self, admin_client, instance):
        db.session.commit()
        html = admin_client.get(
            f'/admin/instances/{instance.id}/edit').get_data(as_text=True)
        assert 'name="topic"' in html

    def test_card_subtitle_shows_topic_and_course(self, admin_client, instance):
        instance.topic = 'PRP у практиці ортопеда'
        db.session.commit()
        html = admin_client.get(
            f'/admin/instances/{instance.id}/edit').get_data(as_text=True)
        assert 'PRP у практиці ортопеда' in html
        assert 'Базовий курс' in html


class TestListings:
    """Тема має стояти там, де захід НАЗИВАЮТЬ, а не лише в його картці."""

    def test_public_course_schedule_shows_topic(self, client, instance):
        instance.topic = 'PRP у практиці ортопеда'
        db.session.commit()
        html = client.get(
            f'/courses/{instance.course.slug}').get_data(as_text=True)
        assert 'PRP у практиці ортопеда' in html

    def test_public_catalog_schedule_shows_topic(self, client, instance):
        instance.topic = 'PRP у практиці ортопеда'
        db.session.commit()
        html = client.get('/courses/').get_data(as_text=True)
        assert 'PRP у практиці ортопеда' in html

    def test_russian_page_shows_the_translated_topic(self, client, instance):
        """Заради цього тему й завели в реєстр перекладів: одна дата не має
        зватись по-різному залежно від мови сторінки."""
        instance.topic = 'PRP у практиці ортопеда'
        instance.set_translation('ru', 'topic', 'PRP в практике ортопеда')
        db.session.commit()
        html = client.get(
            f'/ru/courses/{instance.course.slug}').get_data(as_text=True)
        assert 'PRP в практике ортопеда' in html

    def test_admin_schedule_lists_topic(self, admin_client, instance):
        instance.topic = 'PRP у практиці ортопеда'
        db.session.commit()
        html = admin_client.get('/admin/instances').get_data(as_text=True)
        # Саме підпис рядка, а не aria-label поруч: інакше тест лишався
        # б зеленим і тоді, коли в таблиці стоїть назва курсу.
        assert '<strong>PRP у практиці ортопеда</strong>' in html

    def test_meta_lead_offer_dropdown_shows_topic(self, app, instance):
        """Випадайка прив'язки читає колонки без гідрації моделі -- тема
        мусить підмінятись у самому запиті, інакше менеджер бачить курс."""
        from app.admin.routes_meta_leads import _offer_rows

        instance.topic = 'PRP у практиці ортопеда'
        db.session.flush()
        titles = {row[1] for row in _offer_rows().all()}
        assert 'PRP у практиці ортопеда' in titles
        assert 'Базовий курс' not in titles


class TestTranslationEntry:
    """Тему заводять українською, а показують трьома мовами -- вхід у
    редактор перекладів мусить бути там же, де тему набирають."""

    def test_editor_opens_for_an_instance(self, admin_client, instance):
        instance.topic = 'PRP у практиці ортопеда'
        db.session.commit()
        html = admin_client.get(
            f'/admin/translations/course_instance/{instance.id}'
        ).get_data(as_text=True)
        assert 'PRP у практиці ортопеда' in html
        assert 'Тема' in html

    def test_card_links_to_translations_when_topic_is_set(self, admin_client, instance):
        instance.topic = 'PRP у практиці ортопеда'
        db.session.commit()
        html = admin_client.get(
            f'/admin/instances/{instance.id}/edit').get_data(as_text=True)
        assert f'/admin/translations/course_instance/{instance.id}' in html

    def test_no_translation_link_without_a_topic(self, admin_client, instance):
        db.session.commit()
        html = admin_client.get(
            f'/admin/instances/{instance.id}/edit').get_data(as_text=True)
        assert '/admin/translations/course_instance/' not in html


def test_no_template_names_an_instance_by_its_course_title():
    """Сторож проти напівпройденої заміни.

    Назва проведення береться з `effective_title`. Звертання виду
    `<проведення>.course.title` у шаблоні означає, що це місце заміну
    проґавило -- і сторінка зве захід назвою курсу, поки сусідня зве темою.
    Саме так уже сталося з каталогом `/courses`: перший прохід шукав
    `.course.title` і не побачив перекладної форми `.course.t('title')`.
    """
    import re
    from pathlib import Path

    # Єдиний виняток -- картка проведення: там курс названий НАВМИСНО, як
    # батько теми (підпис "курс: ..." і плейсхолдер поля). Її поведінку
    # тримає TestCard.test_card_subtitle_shows_topic_and_course.
    ALLOWED = {'app/templates/admin/instance_edit.html'}

    templates = Path('app/templates')
    pattern = re.compile(r"\b(inst|instance)\w*\.course\.(title|t\('title'\))")
    offenders = []
    for path in templates.rglob('*.html'):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if pattern.search(line) and path.as_posix() not in ALLOWED:
                offenders.append(f'{path.as_posix()}:{number}')
    assert not offenders, 'проведення назване назвою курсу: ' + ', '.join(offenders)
