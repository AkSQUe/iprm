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

    def test_hint_names_the_consequence_of_filling_the_field(self, app, instance):
        """Підказка мусить називати головний наслідок, а не лише відкат:
        тема йде в сертифікат і в подання до БПР."""
        from app.admin.forms import CourseInstanceForm

        with app.test_request_context():
            form = CourseInstanceForm(obj=instance)
        assert 'назва курсу' in form.topic.description
        assert 'сертифікат' in form.topic.description

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

    def test_schedule_search_finds_by_topic(self, admin_client, instance):
        """Менеджер шукає те, що бачить у рядку. Відколи рядок зветься
        темою, пошук лише по назві курсу перестав знаходити захід."""
        instance.topic = 'PRP у практиці ортопеда'
        db.session.commit()
        html = admin_client.get(
            '/admin/instances?q=ортопеда').get_data(as_text=True)
        assert '<strong>PRP у практиці ортопеда</strong>' in html

    def test_schedule_search_still_finds_by_course_title(self, admin_client, instance):
        instance.topic = 'PRP у практиці ортопеда'
        db.session.commit()
        html = admin_client.get(
            '/admin/instances?q=Базовий').get_data(as_text=True)
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

    def test_new_instance_page_renders_without_an_object(self, admin_client):
        """На створенні сутності ще немає, і макрос вкладок мусить це
        пережити: лічильники перекладу рахуються від obj."""
        resp = admin_client.get('/admin/instances/new')
        assert resp.status_code == 200
        assert 'name="topic"' in resp.get_data(as_text=True)

    def test_card_offers_inline_language_tabs(self, admin_client, instance):
        """Переклад теми має набиратись там же, де тема, -- як у формі курсу."""
        instance.topic = 'PRP у практиці ортопеда'
        db.session.commit()
        html = admin_client.get(
            f'/admin/instances/{instance.id}/edit').get_data(as_text=True)
        assert 'name="tr__ru__topic"' in html
        assert 'name="tr__en__topic"' in html
        assert 'admin-i18n-tabs.js' in html

    def test_topic_and_its_translation_save_in_one_submit(self, admin_client, instance):
        """Порядок важливий: український текст пишеться першим, і лише потім
        переклад -- інакше одиниця перекладу рахувалась би зі старої теми."""
        db.session.commit()
        resp = admin_client.post(f'/admin/instances/{instance.id}/edit', data={
            'course_id': str(instance.course_id),
            'topic': 'PRP у практиці ортопеда',
            'start_date': '2026-12-01T10:00',
            'event_format': 'offline',
            'status': 'published',
            'tr__ru__topic': 'PRP в практике ортопеда',
        }, follow_redirects=True)
        assert resp.status_code == 200

        saved = db.session.get(CourseInstance, instance.id)
        assert saved.topic == 'PRP у практиці ортопеда'
        assert saved.effective_title_for('ru') == 'PRP в практике ортопеда'

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
