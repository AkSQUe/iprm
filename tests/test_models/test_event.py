import pytest
from app.extensions import db
from app.models.event import Event
from app.models.trainer import Trainer
from app.models.program_block import ProgramBlock


def test_event_creation(db_session):
    """Створення заходу з обов'язковими полями."""
    event = Event(title='Test Event', slug='test-event')
    db_session.add(event)
    db_session.flush()

    assert event.id is not None
    assert event.status == 'draft'
    assert event.is_active is True
    assert event.is_featured is False


def test_event_status_label(db_session):
    """Computed property status_label."""
    event = Event(title='E', slug='e', status='published')
    assert event.status_label == 'Опубліковано'


def test_event_type_label(db_session):
    """Computed property event_type_label."""
    event = Event(title='E', slug='e', event_type='course')
    assert event.event_type_label == 'Курс'


def test_event_trainer_relationship(db_session):
    """Зв'язок Event -> Trainer."""
    trainer = Trainer(full_name='Dr. Test', slug='dr-test')
    db_session.add(trainer)
    db_session.flush()

    event = Event(title='E', slug='e', trainer_id=trainer.id)
    db_session.add(event)
    db_session.flush()

    assert event.trainer.full_name == 'Dr. Test'


def test_event_program_blocks_cascade(db_session):
    """Каскадне видалення program_blocks при видаленні event."""
    event = Event(title='E', slug='e-cascade')
    db_session.add(event)
    db_session.flush()

    block = ProgramBlock(event_id=event.id, heading='Block 1', items=['item1'])
    db_session.add(block)
    db_session.flush()

    block_id = block.id
    db_session.delete(event)
    db_session.flush()

    assert db_session.get(ProgramBlock, block_id) is None


def test_event_unique_slug(db_session):
    """Slug має бути унікальним."""
    e1 = Event(title='E1', slug='same-slug')
    db_session.add(e1)
    db_session.flush()

    e2 = Event(title='E2', slug='same-slug')
    db_session.add(e2)
    with pytest.raises(Exception):
        db_session.flush()
