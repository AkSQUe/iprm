from sqlalchemy.orm import contains_eager, joinedload, selectinload

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.program_block import ProgramBlock
from app.models.registration import EventRegistration
from app.models.trainer import Trainer
from app.models.user import User


class TestJoinedLoadQueries:
    """Перевірка що joinedload/selectinload запити працюють коректно."""

    def test_courses_with_joinedload_trainer(self, db_session, sample_course):
        """joinedload(Course.trainer) повертає course з trainer без N+1."""
        courses = Course.query.options(
            joinedload(Course.trainer),
        ).filter(Course.is_active.is_(True)).all()

        assert len(courses) >= 1
        for course in courses:
            if course.trainer:
                assert course.trainer.full_name is not None

    def test_courses_with_selectinload_program_blocks(self, db_session):
        """selectinload(Course.program_blocks) завантажує блоки."""
        course = Course(title='C', slug='c-sel-pb')
        db_session.add(course)
        db_session.flush()

        block = ProgramBlock(course_id=course.id, heading='B', items=['i1'])
        db_session.add(block)
        db_session.flush()

        loaded = Course.query.options(
            selectinload(Course.program_blocks),
        ).filter_by(id=course.id).first()

        assert len(loaded.program_blocks) == 1

    def test_registrations_with_joinedload_user(self, db_session, sample_user, sample_instance):
        """joinedload(EventRegistration.user) повертає user без N+1."""
        reg = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
            phone='+380', specialty='S', workplace='W',
        )
        db_session.add(reg)
        db_session.flush()

        regs = EventRegistration.query.options(
            joinedload(EventRegistration.user),
        ).filter_by(instance_id=sample_instance.id).all()

        assert len(regs) == 1
        assert regs[0].user.email == sample_user.email

    def test_registrations_with_contains_eager_instance(self, db_session, sample_user, sample_instance):
        """contains_eager(EventRegistration.instance) завантажує instance через JOIN."""
        reg = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
            phone='+380', specialty='S', workplace='W',
        )
        db_session.add(reg)
        db_session.flush()

        regs = (
            EventRegistration.query
            .filter_by(user_id=sample_user.id)
            .join(CourseInstance)
            .options(contains_eager(EventRegistration.instance))
            .order_by(CourseInstance.start_date.desc())
            .all()
        )

        assert len(regs) == 1
        assert regs[0].instance.id == sample_instance.id


class TestFilterQueries:
    """Перевірка фільтрів що використовуються в routes."""

    def test_active_courses_filter(self, db_session):
        """Фільтрація активних курсів (головна + catalog)."""
        c1 = Course(title='Active', slug='c-flt-active', is_active=True)
        c2 = Course(title='Inactive', slug='c-flt-inactive', is_active=False)
        db_session.add_all([c1, c2])
        db_session.flush()

        courses = Course.query.filter(Course.is_active.is_(True)).all()
        slugs = [c.slug for c in courses]
        assert 'c-flt-active' in slugs
        assert 'c-flt-inactive' not in slugs

    def test_published_instances_filter(self, db_session, sample_course):
        """Фільтрація published/active instances (public routes)."""
        i1 = CourseInstance(course_id=sample_course.id, status='published')
        i2 = CourseInstance(course_id=sample_course.id, status='draft')
        i3 = CourseInstance(course_id=sample_course.id, status='active')
        db_session.add_all([i1, i2, i3])
        db_session.flush()

        visible = CourseInstance.query.filter(
            CourseInstance.course_id == sample_course.id,
            CourseInstance.status.in_(['published', 'active']),
        ).all()
        ids = [i.id for i in visible]
        assert i1.id in ids
        assert i3.id in ids
        assert i2.id not in ids

    def test_trainer_active_filter(self, db_session):
        """Фільтрація активних тренерів."""
        t1 = Trainer(full_name='Active', slug='t-flt-active', is_active=True)
        t2 = Trainer(full_name='Inactive', slug='t-flt-inactive', is_active=False)
        db_session.add_all([t1, t2])
        db_session.flush()

        trainers = Trainer.query.filter_by(is_active=True).all()
        slugs = [t.slug for t in trainers]
        assert 't-flt-active' in slugs
        assert 't-flt-inactive' not in slugs


class TestSubqueryCount:
    """Перевірка CourseInstance.with_registration_count() -- subquery без N+1."""

    def test_with_registration_count_zero(self, db_session, sample_course):
        """Instance без реєстрацій повертає count=0."""
        inst = CourseInstance(
            course_id=sample_course.id, status='published',
        )
        db_session.add(inst)
        db_session.flush()

        reg_count = CourseInstance.with_registration_count()
        rows = db.session.query(CourseInstance, reg_count).filter(CourseInstance.id == inst.id).all()

        assert len(rows) == 1
        assert rows[0][1] == 0

    def test_with_registration_count_excludes_cancelled(self, db_session, sample_user, sample_instance):
        """Subquery count не рахує скасовані реєстрації."""
        reg1 = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
            phone='+380', specialty='S', workplace='W',
            status='confirmed',
        )
        db_session.add(reg1)
        db_session.flush()

        reg_count = CourseInstance.with_registration_count()
        rows = db.session.query(CourseInstance, reg_count).filter(CourseInstance.id == sample_instance.id).all()

        assert rows[0][1] == 1

    def test_cached_reg_count_used_by_property(self, db_session, sample_instance):
        """registration_count property використовує _cached_reg_count якщо встановлено."""
        sample_instance._cached_reg_count = 42
        assert sample_instance.registration_count == 42


class TestUserRegistrationCount:
    """Перевірка User.with_registration_count() -- subquery замість N+1."""

    def test_user_with_registration_count_zero(self, db_session, sample_user):
        """User без реєстрацій повертає count=0."""
        reg_count = User.with_registration_count()
        rows = db.session.query(User, reg_count).filter(User.id == sample_user.id).all()

        assert len(rows) == 1
        assert rows[0][1] == 0

    def test_user_with_registration_count(self, db_session, sample_user, sample_instance):
        """User з реєстраціями повертає правильний count."""
        reg = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
            phone='+380', specialty='S', workplace='W',
            status='confirmed',
        )
        db_session.add(reg)
        db_session.flush()

        reg_count = User.with_registration_count()
        rows = db.session.query(User, reg_count).filter(User.id == sample_user.id).all()

        assert rows[0][1] == 1

    def test_user_with_registration_count_excludes_cancelled(self, db_session, sample_user, sample_instance):
        """User subquery count не рахує скасовані реєстрації."""
        reg = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
            phone='+380', specialty='S', workplace='W',
            status='cancelled',
        )
        db_session.add(reg)
        db_session.flush()

        reg_count = User.with_registration_count()
        rows = db.session.query(User, reg_count).filter(User.id == sample_user.id).all()

        assert rows[0][1] == 0

    def test_user_cached_reg_count_used_by_property(self, db_session, sample_user):
        """registration_count property використовує _cached_reg_count якщо встановлено."""
        sample_user._cached_reg_count = 7
        assert sample_user.registration_count == 7


# ---- перф-інваріант каталогу ------------------------------------------------

def _count_selects(client, url):
    """Скільки SELECT-ів коштує одна віддача сторінки."""
    from sqlalchemy import event

    counted = []

    def _count(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith('SELECT'):
            counted.append(statement)

    event.listen(db.engine, 'before_cursor_execute', _count)
    try:
        assert client.get(url).status_code == 200
    finally:
        event.remove(db.engine, 'before_cursor_execute', _count)
    return len(counted)


def _add_instances(db_session, course, count, start_at=30):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    for k in range(count):
        db_session.add(CourseInstance(
            course_id=course.id,
            start_date=now + timedelta(days=start_at + k),
            end_date=now + timedelta(days=start_at + k, hours=4),
            event_format='offline', status='published', price=500,
        ))
    db_session.flush()


def test_catalog_query_count_does_not_grow_with_instances(
        client, db_session, sample_course, sample_user):
    """Каталог не має дорожчати з кожним проведенням -- і для залогіненого теж.

    Картка календаря бере готовий рядок балів БПР із `render_template`, і той
    виклик -- повноцінний рендер Flask: на КОЖНОМУ з них заново відпрацьовують
    усі context processors. Один із них (`inject_certdata_reminder`) робить
    запит до `event_registrations`, тож сторінка коштувала один SELECT на
    кожне проведення -- але лише для залогіненого користувача, бо анонім
    виходить із процесора раніше. Тому міряємо саме під логіном.

    Міряємо ПРИРІСТ, а не абсолют: постійна ціна сторінки залежить від речей
    поза цим тестом, і поріг на абсолютне число ламався б від чужих тестів.

    Профіль користувачу навмисно не створюємо: із заповненою анкетою процесор
    виходить до запиту, і тест перестав би стерегти те, заради чого написаний.
    """
    from tests.support.rbac import switch_user

    switch_user(client, sample_user)

    _add_instances(db_session, sample_course, 1)
    client.get('/courses/')
    baseline = _count_selects(client, '/courses/')

    _add_instances(db_session, sample_course, 5, start_at=60)
    # Тестова сесія живе через усі запити тесту, і вже завантажену колекцію
    # `course.instances` наступний selectinload не перечитує -- без цього
    # рядка друга віддача каталогу показувала б старі проведення, а тест
    # мовчки не міряв би нічого. У проді кожен запит має власну сесію.
    db_session.expire_all()
    client.get('/courses/')
    grown = _count_selects(client, '/courses/')

    assert grown - baseline <= 1, (
        f'+5 проведень додали {grown - baseline} запитів '
        f'({baseline} -> {grown}): рендер картки тягне запит на кожне проведення'
    )


def test_catalog_cpd_text_stays_localized(client, db_session, sample_course):
    """Рядок балів у картці календаря лишається перекладеним.

    `_cpd_text` рендерить партіал повз `render_template` -- саме тим і дешевий.
    Ціна помилки тут: фільтри й gettext живуть у jinja_env, і якби переклад
    брався з контексту запиту, англійська й російська картки мовчки поїхали б
    українською, а помітили б це не тестом, а на проді.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    # Гібрид: два формати з РІЗНИМИ балами -- лише ця гілка макроса друкує
    # слова "Онлайн"/"Офлайн", тобто лише вона взагалі щось перекладає.
    db_session.add(CourseInstance(
        course_id=sample_course.id,
        start_date=now + timedelta(days=10),
        end_date=now + timedelta(days=10, hours=4),
        event_format='hybrid', status='published', price=500,
        cpd_points_online=3, cpd_points_offline=5,
    ))
    db_session.flush()

    # Flask-Babel кешує обрану локаль на `g`, а session-scoped app-фікстура
    # тримає один app-контекст на всі запити тесту -- без скидання друга
    # віддача просто повторила б мову першої (ідіома tests/test_i18n/conftest).
    from flask import g

    g.pop('_flask_babel', None)
    uk = client.get('/courses/').get_data(as_text=True)
    g.pop('_flask_babel', None)
    en = client.get('/en/courses/').get_data(as_text=True)
    # Прибираємо за собою: інакше наступний тест у цьому ж app-контексті
    # успадкував би закешовану англійську й упав би за кілометр звідси.
    g.pop('_flask_babel', None)

    assert 'Онлайн' in uk
    assert 'Online' in en
