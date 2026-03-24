from app.models.event import Event
from app.models.trainer import Trainer
from app.models.clinic import Clinic


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
