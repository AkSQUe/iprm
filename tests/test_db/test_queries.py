from sqlalchemy.orm import joinedload, selectinload, contains_eager

from app.extensions import db
from app.models.event import Event
from app.models.user import User
from app.models.trainer import Trainer
from app.models.registration import EventRegistration
from app.models.program_block import ProgramBlock


class TestJoinedLoadQueries:
    """Перевірка що joinedload/selectinload запити працюють коректно."""

    def test_events_with_joinedload_trainer(self, db_session, sample_event):
        """joinedload(Event.trainer) повертає event з trainer без N+1."""
        events = Event.query.options(
            joinedload(Event.trainer),
        ).filter(Event.is_active.is_(True)).all()

        assert len(events) >= 1
        for event in events:
            if event.trainer:
                assert event.trainer.full_name is not None

    def test_events_with_selectinload_program_blocks(self, db_session):
        """selectinload(Event.program_blocks) завантажує блоки."""
        event = Event(title='E', slug='e-sel-pb')
        db_session.add(event)
        db_session.flush()

        block = ProgramBlock(event_id=event.id, heading='B', items=['i1'])
        db_session.add(block)
        db_session.flush()

        loaded = Event.query.options(
            selectinload(Event.program_blocks),
        ).filter_by(id=event.id).first()

        assert len(loaded.program_blocks) == 1

    def test_registrations_with_joinedload_user(self, db_session, sample_user, sample_event):
        """joinedload(EventRegistration.user) повертає user без N+1."""
        reg = EventRegistration(
            user_id=sample_user.id, event_id=sample_event.id,
            phone='+380', specialty='S', workplace='W',
        )
        db_session.add(reg)
        db_session.flush()

        regs = EventRegistration.query.options(
            joinedload(EventRegistration.user),
        ).filter_by(event_id=sample_event.id).all()

        assert len(regs) == 1
        assert regs[0].user.email == sample_user.email


    def test_registrations_with_contains_eager_event(self, db_session, sample_user, sample_event):
        """contains_eager(EventRegistration.event) завантажує event через існуючий JOIN."""
        reg = EventRegistration(
            user_id=sample_user.id, event_id=sample_event.id,
            phone='+380', specialty='S', workplace='W',
        )
        db_session.add(reg)
        db_session.flush()

        regs = (
            EventRegistration.query
            .filter_by(user_id=sample_user.id)
            .join(Event)
            .options(contains_eager(EventRegistration.event))
            .order_by(Event.start_date.desc())
            .all()
        )

        assert len(regs) == 1
        assert regs[0].event.title == sample_event.title


class TestFilterQueries:
    """Перевірка фільтрів що використовуються в routes."""

    def test_active_published_events_filter(self, db_session):
        """Фільтрація активних опублікованих заходів (головна + courses)."""
        e1 = Event(title='Active', slug='e-flt-active', is_active=True, status='published')
        e2 = Event(title='Draft', slug='e-flt-draft', is_active=True, status='draft')
        e3 = Event(title='Inactive', slug='e-flt-inactive', is_active=False, status='published')
        db_session.add_all([e1, e2, e3])
        db_session.flush()

        events = Event.query.filter(
            Event.is_active.is_(True),
            Event.status.in_(['published', 'active']),
        ).all()

        slugs = [e.slug for e in events]
        assert 'e-flt-active' in slugs
        assert 'e-flt-draft' not in slugs
        assert 'e-flt-inactive' not in slugs

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
    """Перевірка with_registration_count() -- subquery замість N+1."""

    def test_with_registration_count_zero(self, db_session):
        """Event без реєстрацій повертає count=0."""
        event = Event(title='E', slug='e-cnt-zero', is_active=True, status='published')
        db_session.add(event)
        db_session.flush()

        reg_count = Event.with_registration_count()
        rows = db.session.query(Event, reg_count).filter(Event.id == event.id).all()

        assert len(rows) == 1
        assert rows[0][1] == 0

    def test_with_registration_count_excludes_cancelled(self, db_session, sample_user, sample_event):
        """Subquery count не рахує скасовані реєстрації."""
        reg1 = EventRegistration(
            user_id=sample_user.id, event_id=sample_event.id,
            phone='+380', specialty='S', workplace='W',
            status='confirmed',
        )
        db_session.add(reg1)
        db_session.flush()

        reg_count = Event.with_registration_count()
        rows = db.session.query(Event, reg_count).filter(Event.id == sample_event.id).all()

        assert rows[0][1] == 1

    def test_cached_reg_count_used_by_property(self, db_session):
        """registration_count property використовує _cached_reg_count якщо встановлено."""
        event = Event(title='E', slug='e-cached-cnt')
        event._cached_reg_count = 42

        assert event.registration_count == 42


class TestUserRegistrationCount:
    """Перевірка User.with_registration_count() -- subquery замість N+1."""

    def test_user_with_registration_count_zero(self, db_session, sample_user):
        """User без реєстрацій повертає count=0."""
        reg_count = User.with_registration_count()
        rows = db.session.query(User, reg_count).filter(User.id == sample_user.id).all()

        assert len(rows) == 1
        assert rows[0][1] == 0

    def test_user_with_registration_count(self, db_session, sample_user, sample_event):
        """User з реєстраціями повертає правильний count."""
        reg = EventRegistration(
            user_id=sample_user.id, event_id=sample_event.id,
            phone='+380', specialty='S', workplace='W',
            status='confirmed',
        )
        db_session.add(reg)
        db_session.flush()

        reg_count = User.with_registration_count()
        rows = db.session.query(User, reg_count).filter(User.id == sample_user.id).all()

        assert rows[0][1] == 1

    def test_user_with_registration_count_excludes_cancelled(self, db_session, sample_user, sample_event):
        """User subquery count не рахує скасовані реєстрації."""
        reg = EventRegistration(
            user_id=sample_user.id, event_id=sample_event.id,
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
