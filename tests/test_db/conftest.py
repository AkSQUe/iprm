import pytest
from app.models.user import User
from app.models.event import Event
from app.models.trainer import Trainer


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
    )
    db_session.add(event)
    db_session.flush()
    return event
