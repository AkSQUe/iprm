from app.models.event import Event
from app.models.user import User
from app.models.trainer import Trainer
from app.models.clinic import Clinic
from app.models.email_log import EmailLog


class TestIndexedOrderBy:
    """Перевірка що order_by на індексованих колонках працює коректно."""

    def test_events_order_by_start_date(self, db_session):
        """Сортування заходів по індексованому start_date."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)

        e1 = Event(title='Later', slug='e-idx-later', start_date=now + timedelta(days=7))
        e2 = Event(title='Sooner', slug='e-idx-sooner', start_date=now + timedelta(days=1))
        db_session.add_all([e1, e2])
        db_session.flush()

        events = Event.query.order_by(Event.start_date).all()
        dates = [e.start_date for e in events if e.start_date]
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

    def test_events_filter_by_status_indexed(self, db_session):
        """Фільтрація по індексованому полю status."""
        e1 = Event(title='Pub', slug='e-idx-pub', status='published')
        e2 = Event(title='Draft', slug='e-idx-draft', status='draft')
        db_session.add_all([e1, e2])
        db_session.flush()

        published = Event.query.filter_by(status='published').all()
        slugs = [e.slug for e in published]
        assert 'e-idx-pub' in slugs
        assert 'e-idx-draft' not in slugs

    def test_events_order_by_created_at(self, db_session):
        """Сортування заходів по індексованому created_at (admin)."""
        e1 = Event(title='First', slug='e-idx-ca-1')
        db_session.add(e1)
        db_session.flush()

        e2 = Event(title='Second', slug='e-idx-ca-2')
        db_session.add(e2)
        db_session.flush()

        events = Event.query.order_by(Event.created_at.desc()).all()
        assert len(events) >= 2

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
