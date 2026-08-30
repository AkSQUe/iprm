"""Сторінка Meta-форм: що показує і що дозволяє змінити.

Сторінка існує заради однієї дії -- сказати системі, про який захід кожна
форма. Усе інше на ній довідкове.

Межа, яку легко зламати: випадайка мусить показувати ВЖЕ ПРИВ'ЯЗАНИЙ захід
навіть тоді, коли він минув. Інакше відкриття сторінки мовчки показувало б
«не обрано» там, де прив'язка є, і перше ж збереження її б стерло.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.meta_lead import MetaLeadForm
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'mf-adm-{_uid()}@test.com', 'password123',
        first_name='М', last_name='Адмін', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return user


@pytest.fixture
def plain_user(app):
    user = User.create_with_password(
        f'mf-usr-{_uid()}@test.com', 'password123',
        first_name='Б', last_name='Юзер', email_confirmed=True,
    )
    db.session.flush()
    return user


# Прибирання за собою: користувачі комітяться роутами адмінки, тож без
# цього рядки цього файлу протікали б у чужі вибірки -- і падав би не цей
# тест, а сусідній. Той самий патерн, що в tests/test_routes/test_meta_admin.py.
_OWNED_MODELS = (MetaLeadForm, CourseInstance, Course, User)


def _ids(model):
    return {row_id for (row_id,) in db.session.query(model.id).all()}


@pytest.fixture(autouse=True)
def cleanup(app):
    before = {model: _ids(model) for model in _OWNED_MODELS}
    yield
    db.session.rollback()
    for model in _OWNED_MODELS:
        for row in model.query.all():
            if row.id not in before[model]:
                db.session.delete(row)
        db.session.flush()
    db.session.commit()


def _instance(days, status='published'):
    course = Course(title=f'Курс {days}', slug=f'c{days}-{uuid4().hex[:6]}')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status=status,
        start_date=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.session.add(instance)
    db.session.flush()
    return instance


def test_page_lists_synced_forms(client, admin):
    _login(client, admin)
    db.session.add(MetaLeadForm(form_id='900', name='Плазмотерапія',
                                questions={'q': {'label': 'Питання'}}))
    db.session.flush()

    page = client.get('/admin/meta-leads/forms')

    assert page.status_code == 200
    assert 'Плазмотерапія'.encode() in page.data


def test_offer_can_be_attached(client, admin):
    _login(client, admin)
    form = MetaLeadForm(form_id='901', questions={})
    db.session.add(form)
    db.session.flush()
    instance = _instance(14)

    client.post(f'/admin/meta-leads/forms/{form.id}/offer',
                data={'course_instance_id': str(instance.id)},
                follow_redirects=True)

    assert MetaLeadForm.query.get(form.id).course_instance_id == instance.id


def test_offer_can_be_detached(client, admin):
    _login(client, admin)
    instance = _instance(14)
    form = MetaLeadForm(form_id='902', questions={},
                        course_instance_id=instance.id)
    db.session.add(form)
    db.session.flush()

    client.post(f'/admin/meta-leads/forms/{form.id}/offer',
                data={'course_instance_id': ''},
                follow_redirects=True)

    assert MetaLeadForm.query.get(form.id).course_instance_id is None


def test_past_event_stays_visible_when_attached(client, admin):
    """Минулий, але прив'язаний захід має лишатись у списку варіантів."""
    _login(client, admin)
    past = _instance(-30)
    form = MetaLeadForm(form_id='903', questions={},
                        course_instance_id=past.id)
    db.session.add(form)
    db.session.flush()

    body = client.get('/admin/meta-leads/forms').data.decode()

    assert f'value="{past.id}" selected' in body


def test_page_requires_admin(client, plain_user):
    _login(client, plain_user)

    assert client.get('/admin/meta-leads/forms').status_code in (302, 403, 404)
