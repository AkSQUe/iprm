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


def test_offer_choices_query_base_list_once(client, admin, monkeypatch):
    """Базовий список живих заходів рахується ОДИН раз для всієї сторінки.

    Раніше кожна форма викликала той самий SELECT наново (K форм -- K
    однакових запитів там, де досить одного): зріз живих заходів той самий
    для кожного рядка таблиці. Форм сьогодні десятки, тож болю не було, але
    це рівно той шаблон, який наступний скопіює в місце, де форм будуть
    тисячі. Лічимо виклики `_base_offer_choices`, а не самі SELECT -- це і є
    межа, яку легко порушити знову.
    """
    from app.admin import routes_meta_leads

    calls = []
    original = routes_meta_leads._base_offer_choices

    def _counting():
        calls.append(1)
        return original()

    monkeypatch.setattr(routes_meta_leads, '_base_offer_choices', _counting)

    _login(client, admin)
    for i in range(3):
        db.session.add(MetaLeadForm(form_id=f'91{i}', questions={}))
    db.session.flush()

    page = client.get('/admin/meta-leads/forms')

    assert page.status_code == 200
    assert len(calls) == 1, f'очікували один запит бази, отримали {len(calls)}'


def test_sync_forms_returns_to_the_forms_page(client, admin):
    """Кнопка живе на сторінці форм -- і повертати мусить на неї.

    Порожній стан цієї ж сторінки прямо каже «Натисніть „Оновити підписи
    форм“». Редирект на Налаштування викидав адміна туди, де цієї кнопки
    вже немає.
    """
    from app.models.site_settings import SiteSettings

    settings = SiteSettings.get()
    before = settings.meta_page_id
    settings.meta_page_id = ''
    db.session.flush()
    _login(client, admin)

    page = client.post('/admin/meta-leads/settings/sync-forms')

    settings.meta_page_id = before
    db.session.flush()
    assert page.status_code == 302
    assert page.headers['Location'].endswith('/admin/meta-leads/forms')


def test_offer_dropdown_does_not_load_heavy_relations(client, admin):
    """Випадайка бере рівно id, назву й дату -- і нічого більше.

    `CourseInstance.material_reservations` і `Course.material_kits`
    оголошені `lazy='selectin'`, тож завантаження заходу цілком тягло за
    собою ще два SELECT на КОЖЕН варіант випадайки.
    """
    from sqlalchemy import event as sa_event

    _login(client, admin)
    for i in range(3):
        _instance(10 + i)
    db.session.add(MetaLeadForm(form_id='920', questions={}))
    db.session.flush()

    statements = []

    def _record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    sa_event.listen(db.engine, 'before_cursor_execute', _record)
    try:
        page = client.get('/admin/meta-leads/forms')
    finally:
        sa_event.remove(db.engine, 'before_cursor_execute', _record)

    assert page.status_code == 200
    heavy = [s for s in statements
             if 'material_reservations' in s or 'material_kits' in s]
    assert heavy == [], f'важкі зв\'язки підвантажились: {len(heavy)} запит(ів)'


def test_active_form_is_not_painted_as_a_draft(client, admin):
    """Стан форми має читатись: активна -- не чернетка."""
    _login(client, admin)
    db.session.add(MetaLeadForm(form_id='930', name='Активна', status='ACTIVE',
                                questions={}))
    db.session.add(MetaLeadForm(form_id='931', name='Архівна',
                                status='ARCHIVED', questions={}))
    db.session.flush()

    body = client.get('/admin/meta-leads/forms').data.decode()

    assert 'badge--active' in body
    assert 'badge--completed' in body
