from app.models.clinic import Clinic
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.email_log import EmailLog
from app.models.trainer import Trainer
from app.models.user import User


class TestIndexedOrderBy:
    """Перевірка що order_by на індексованих колонках працює коректно."""

    def test_instances_order_by_start_date(self, db_session, sample_course):
        """Сортування проведень по індексованому start_date."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)

        i1 = CourseInstance(course_id=sample_course.id, start_date=now + timedelta(days=7))
        i2 = CourseInstance(course_id=sample_course.id, start_date=now + timedelta(days=1))
        db_session.add_all([i1, i2])
        db_session.flush()

        instances = CourseInstance.query.filter_by(course_id=sample_course.id).order_by(CourseInstance.start_date).all()
        dates = [i.start_date for i in instances if i.start_date]
        assert dates == sorted(dates)

    def test_trainers_order_by_full_name(self, db_session):
        """Сортування тренерів по індексованому full_name."""
        t1 = Trainer(full_name='Zelinsky', slug='t-idx-z')
        t2 = Trainer(full_name='Andriyenko', slug='t-idx-a')
        db_session.add_all([t1, t2])
        db_session.flush()

        trainers = Trainer.query.order_by(Trainer.full_name).all()
        names = [t.full_name for t in trainers]
        assert names == sorted(names)

    def test_clinics_order_by_sort_order(self, db_session):
        """Сортування клінік по індексованому sort_order."""
        c1 = Clinic(name='Third', slug='c-idx-3', sort_order=3)
        c2 = Clinic(name='First', slug='c-idx-1', sort_order=1)
        c3 = Clinic(name='Second', slug='c-idx-2', sort_order=2)
        db_session.add_all([c1, c2, c3])
        db_session.flush()

        clinics = Clinic.query.order_by(Clinic.sort_order).all()
        assert clinics[0].name == 'First'
        assert clinics[1].name == 'Second'
        assert clinics[2].name == 'Third'

    def test_instances_filter_by_status_indexed(self, db_session, sample_course):
        """Фільтрація по індексованому полю status."""
        i1 = CourseInstance(course_id=sample_course.id, status='published')
        i2 = CourseInstance(course_id=sample_course.id, status='draft')
        db_session.add_all([i1, i2])
        db_session.flush()

        published = CourseInstance.query.filter_by(
            course_id=sample_course.id, status='published',
        ).all()
        assert len(published) == 1
        assert published[0].id == i1.id

    def test_courses_order_by_created_at(self, db_session):
        """Сортування курсів по індексованому created_at (admin)."""
        c1 = Course(title='First', slug='c-idx-ca-1')
        db_session.add(c1)
        db_session.flush()

        c2 = Course(title='Second', slug='c-idx-ca-2')
        db_session.add(c2)
        db_session.flush()

        courses = Course.query.order_by(Course.created_at.desc()).all()
        assert len(courses) >= 2

    def test_users_order_by_created_at(self, db_session):
        """Сортування користувачів по індексованому created_at (admin)."""
        u1 = User(email='idx-u1@test.com', password='pass1234')
        db_session.add(u1)
        db_session.flush()

        u2 = User(email='idx-u2@test.com', password='pass1234')
        db_session.add(u2)
        db_session.flush()

        users = User.query.order_by(User.created_at.desc()).all()
        assert len(users) >= 2

    def test_email_logs_filter_by_status_and_trigger(self, db_session):
        """Фільтрація email_logs по composite index (status, trigger)."""
        log1 = EmailLog(
            to_email='a@test.com', subject='S1',
            template_name='t1', status='sent', trigger='registration',
        )
        log2 = EmailLog(
            to_email='b@test.com', subject='S2',
            template_name='t2', status='failed', trigger='payment',
        )
        db_session.add_all([log1, log2])
        db_session.flush()

        results = EmailLog.query.filter(
            EmailLog.status == 'sent',
            EmailLog.trigger == 'registration',
        ).all()
        assert len(results) >= 1
        assert all(r.status == 'sent' and r.trigger == 'registration' for r in results)
