import pytest
from app.models.user import User
from app.models.event import Event
from app.models.trainer import Trainer
from app.models.clinic import Clinic
from app.models.registration import EventRegistration


class TestUniqueConstraints:
    """Перевірка UNIQUE constraints на рівні БД."""

    def test_user_email_unique(self, db_session):
        """Два користувача не можуть мати однаковий email."""
        u1 = User(email='dup@test.com', password='pass1234')
        db_session.add(u1)
        db_session.flush()

        u2 = User(email='dup@test.com', password='pass5678')
        db_session.add(u2)
        with pytest.raises(Exception):
            db_session.flush()

    def test_event_slug_unique(self, db_session):
        """Slug заходу має бути унікальним."""
        e1 = Event(title='E1', slug='same-slug')
        db_session.add(e1)
        db_session.flush()

        e2 = Event(title='E2', slug='same-slug')
        db_session.add(e2)
        with pytest.raises(Exception):
            db_session.flush()

    def test_trainer_slug_unique(self, db_session):
        """Slug тренера має бути унікальним."""
        t1 = Trainer(full_name='T1', slug='same-slug')
        db_session.add(t1)
        db_session.flush()

        t2 = Trainer(full_name='T2', slug='same-slug')
        db_session.add(t2)
        with pytest.raises(Exception):
            db_session.flush()

    def test_clinic_slug_unique(self, db_session):
        """Slug клініки має бути унікальним."""
        c1 = Clinic(name='C1', slug='same-slug')
        db_session.add(c1)
        db_session.flush()

        c2 = Clinic(name='C2', slug='same-slug')
        db_session.add(c2)
        with pytest.raises(Exception):
            db_session.flush()

    def test_registration_one_per_user_event(self, db_session, sample_user, sample_event):
        """Один користувач може зареєструватись на захід лише раз."""
        reg1 = EventRegistration(
            user_id=sample_user.id, event_id=sample_event.id,
            phone='+380501234567', specialty='S', workplace='W',
        )
        db_session.add(reg1)
        db_session.flush()

        reg2 = EventRegistration(
            user_id=sample_user.id, event_id=sample_event.id,
            phone='+380501234567', specialty='S', workplace='W',
        )
        db_session.add(reg2)
        with pytest.raises(Exception):
            db_session.flush()


class TestDefaultValues:
    """Перевірка default values на моделях."""

    def test_event_defaults(self, db_session):
        """Захід створюється з правильними defaults."""
        event = Event(title='E', slug='e-defaults')
        db_session.add(event)
        db_session.flush()

        assert event.status == 'draft'
        assert event.is_active is True
        assert event.is_featured is False
        assert event.price == 0

    def test_user_defaults(self, db_session):
        """Користувач створюється з правильними defaults."""
        user = User(email='def@test.com', password='pass1234')
        db_session.add(user)
        db_session.flush()

        assert user.is_active is True
        assert user.is_admin is False

    def test_registration_defaults(self, db_session, sample_user, sample_event):
        """Реєстрація створюється з правильними defaults."""
        reg = EventRegistration(
            user_id=sample_user.id, event_id=sample_event.id,
            phone='+380', specialty='S', workplace='W',
        )
        db_session.add(reg)
        db_session.flush()

        assert reg.status == 'pending'
        assert reg.payment_status == 'unpaid'
        assert reg.attended is False

    def test_clinic_defaults(self, db_session):
        """Клініка створюється з правильними defaults."""
        clinic = Clinic(name='C', slug='c-defaults')
        db_session.add(clinic)
        db_session.flush()

        assert clinic.sort_order == 0
        assert clinic.is_active is True


class TestCheckConstraints:
    """Перевірка CHECK constraints на рівні БД (SQLite не підтримує всі CHECK)."""

    def test_event_max_participants_zero_rejected(self, db_session):
        """CHECK constraint: max_participants не може бути 0."""
        event = Event(title='E', slug='e-ck-mp-zero', max_participants=0)
        db_session.add(event)
        with pytest.raises(Exception):
            db_session.flush()

    def test_event_max_participants_negative_rejected(self, db_session):
        """CHECK constraint: max_participants не може бути від'ємним."""
        event = Event(title='E', slug='e-ck-mp-neg', max_participants=-1)
        db_session.add(event)
        with pytest.raises(Exception):
            db_session.flush()

    def test_event_max_participants_null_allowed(self, db_session):
        """max_participants NULL допустимий (необмежена кількість)."""
        event = Event(title='E', slug='e-ck-mp-null', max_participants=None)
        db_session.add(event)
        db_session.flush()
        assert event.max_participants is None

    def test_event_max_participants_positive_allowed(self, db_session):
        """max_participants >= 1 допустимий."""
        event = Event(title='E', slug='e-ck-mp-pos', max_participants=30)
        db_session.add(event)
        db_session.flush()
        assert event.max_participants == 30


class TestTimestamps:
    """Перевірка автоматичних timestamps."""

    def test_user_timestamps(self, db_session):
        """created_at та updated_at заповнюються автоматично."""
        user = User(email='ts@test.com', password='pass1234')
        db_session.add(user)
        db_session.flush()

        assert user.created_at is not None
        assert user.updated_at is not None

    def test_event_timestamps(self, db_session):
        """created_at та updated_at заповнюються автоматично."""
        event = Event(title='E', slug='e-ts')
        db_session.add(event)
        db_session.flush()

        assert event.created_at is not None
        assert event.updated_at is not None
