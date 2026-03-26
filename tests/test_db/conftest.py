import pytest
from app.models.user import User
from app.models.event import Event
from app.models.trainer import Trainer
from app.models.registration import EventRegistration
from app.models.payment_transaction import PaymentTransaction


@pytest.fixture
def sample_user(db_session):
    """Базовий користувач для db-тестів."""
    user = User(email='db-test@example.com', password='testpass123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def sample_trainer(db_session):
    """Базовий тренер для db-тестів."""
    trainer = Trainer(full_name='Dr. Testov', slug='dr-testov')
    db_session.add(trainer)
    db_session.flush()
    return trainer


@pytest.fixture
def sample_event(db_session, sample_trainer):
    """Базовий захід для db-тестів."""
    event = Event(
        title='Test Event',
        slug='test-event-db',
        status='published',
        is_active=True,
        trainer_id=sample_trainer.id,
        price=500,
    )
    db_session.add(event)
    db_session.flush()
    return event


@pytest.fixture
def sample_registration(db_session, sample_user, sample_event):
    """Базова реєстрація для db-тестів."""
    reg = EventRegistration(
        user_id=sample_user.id,
        event_id=sample_event.id,
        phone='+380501234567',
        specialty='Cardiology',
        workplace='City Hospital',
        status='confirmed',
        payment_status='paid',
        payment_amount=500,
    )
    db_session.add(reg)
    db_session.flush()
    return reg


@pytest.fixture
def sample_transaction(db_session, sample_registration):
    """Базова платіжна транзакція для db-тестів."""
    txn = PaymentTransaction(
        registration_id=sample_registration.id,
        order_id=f'REG-{sample_registration.id}',
        liqpay_status='success',
        mapped_status='paid',
        amount=500,
        source='callback',
    )
    db_session.add(txn)
    db_session.flush()
    return txn
