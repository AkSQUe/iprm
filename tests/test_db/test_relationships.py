from app.models.user import User
from app.models.event import Event
from app.models.trainer import Trainer
from app.models.program_block import ProgramBlock
from app.models.registration import EventRegistration


class TestEventRelationships:
    """Зв'язки моделі Event."""

    def test_event_trainer_back_populates(self, db_session, sample_trainer):
        """Двосторонній зв'язок Event <-> Trainer."""
        event = Event(title='E', slug='e-bp-trainer', trainer_id=sample_trainer.id)
        db_session.add(event)
        db_session.flush()

        assert event.trainer.full_name == sample_trainer.full_name
        assert sample_trainer.events.count() == 1

    def test_event_creator_back_populates(self, db_session, sample_user):
        """Двосторонній зв'язок Event.creator <-> User.created_events."""
        event = Event(title='E', slug='e-creator', created_by=sample_user.id)
        db_session.add(event)
        db_session.flush()

        assert event.creator.email == sample_user.email
        assert len(sample_user.created_events) == 1
        assert sample_user.created_events[0].slug == 'e-creator'

    def test_event_cascade_deletes_program_blocks(self, db_session):
        """CASCADE: видалення event видаляє пов'язані program_blocks."""
        event = Event(title='E', slug='e-cascade-pb')
        db_session.add(event)
        db_session.flush()

        block = ProgramBlock(event_id=event.id, heading='B', items=['i1'])
        db_session.add(block)
        db_session.flush()

        block_id = block.id
        db_session.delete(event)
        db_session.flush()

        assert db_session.get(ProgramBlock, block_id) is None

    def test_event_registrations_back_populates(self, db_session, sample_user):
        """Двосторонній зв'язок Event <-> EventRegistration."""
        event = Event(title='E', slug='e-reg-bp')
        db_session.add(event)
        db_session.flush()

        reg = EventRegistration(
            user_id=sample_user.id, event_id=event.id,
            phone='+380', specialty='S', workplace='W',
        )
        db_session.add(reg)
        db_session.flush()

        assert event.registrations.count() == 1
        assert reg.event.title == 'E'


class TestTrainerRelationships:
    """Зв'язки моделі Trainer."""

    def test_trainer_events_dynamic(self, db_session, sample_trainer):
        """Trainer.events -- dynamic relationship з фільтрацією."""
        e1 = Event(title='Active', slug='e-t-active', trainer_id=sample_trainer.id, is_active=True)
        e2 = Event(title='Inactive', slug='e-t-inactive', trainer_id=sample_trainer.id, is_active=False)
        db_session.add_all([e1, e2])
        db_session.flush()

        assert sample_trainer.events.count() == 2
        assert sample_trainer.events.filter_by(is_active=True).count() == 1


class TestRegistrationRelationships:
    """Зв'язки моделі EventRegistration."""

    def test_registration_user_back_populates(self, db_session, sample_user, sample_event):
        """Двосторонній зв'язок EventRegistration <-> User."""
        reg = EventRegistration(
            user_id=sample_user.id, event_id=sample_event.id,
            phone='+380', specialty='S', workplace='W',
        )
        db_session.add(reg)
        db_session.flush()

        assert reg.user.email == sample_user.email
        assert sample_user.registrations.count() == 1


class TestProgramBlockRelationships:
    """Зв'язки моделі ProgramBlock."""

    def test_program_block_event_back_populates(self, db_session):
        """Двосторонній зв'язок ProgramBlock <-> Event."""
        event = Event(title='Parent', slug='e-pb-bp')
        db_session.add(event)
        db_session.flush()

        block = ProgramBlock(event_id=event.id, heading='B', items=[])
        db_session.add(block)
        db_session.flush()

        assert block.event.title == 'Parent'
        assert len(event.program_blocks) == 1

    def test_program_block_ordering(self, db_session):
        """Блоки програми сортуються за sort_order."""
        event = Event(title='E', slug='e-pb-sort')
        db_session.add(event)
        db_session.flush()

        b1 = ProgramBlock(event_id=event.id, heading='Second', items=[], sort_order=2)
        b2 = ProgramBlock(event_id=event.id, heading='First', items=[], sort_order=1)
        db_session.add_all([b1, b2])
        db_session.flush()

        blocks = event.program_blocks
        assert blocks[0].heading == 'First'
        assert blocks[1].heading == 'Second'
