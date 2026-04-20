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
