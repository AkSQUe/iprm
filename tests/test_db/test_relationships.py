import pytest
from app.models.user import User
from app.models.event import Event
from app.models.trainer import Trainer
from app.models.program_block import ProgramBlock
from app.models.registration import EventRegistration
from app.models.payment_transaction import PaymentTransaction


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


class TestPaymentTransactionRelationships:
    """Зв'язки моделі PaymentTransaction."""

    def test_transaction_registration_back_populates(self, db_session, sample_registration):
        """Двосторонній зв'язок PaymentTransaction <-> EventRegistration."""
        txn = PaymentTransaction(
            registration_id=sample_registration.id,
            order_id=f'REG-{sample_registration.id}',
            mapped_status='paid',
            source='callback',
        )
        db_session.add(txn)
        db_session.flush()

        assert txn.registration.id == sample_registration.id
        assert sample_registration.payment_transactions.count() == 1

    def test_transaction_cascade_on_registration_delete(self, db_session, sample_user):
        """CASCADE: FK ondelete='CASCADE' налаштовано на payment_transactions.registration_id."""
        from app.extensions import db as _db

        event = Event(title='E', slug='e-txn-cascade', price=100)
        db_session.add(event)
        db_session.flush()

        reg = EventRegistration(
            user_id=sample_user.id, event_id=event.id,
            phone='+380', specialty='S', workplace='W',
            payment_amount=100,
        )
        db_session.add(reg)
        db_session.flush()

        txn = PaymentTransaction(
            registration_id=reg.id,
            order_id=f'REG-{reg.id}',
            mapped_status='paid',
            source='callback',
        )
        db_session.add(txn)
        db_session.flush()

        fk = PaymentTransaction.__table__.c.registration_id.foreign_keys
        fk_obj = next(iter(fk))
        assert fk_obj.ondelete == 'CASCADE'
        assert txn.registration_id == reg.id

    def test_multiple_transactions_per_registration(self, db_session, sample_registration):
        """Одна реєстрація може мати кілька транзакцій (аудит)."""
        txn1 = PaymentTransaction(
            registration_id=sample_registration.id,
            order_id=f'REG-{sample_registration.id}',
            mapped_status='pending',
            source='callback',
            liqpay_status='processing',
        )
        txn2 = PaymentTransaction(
            registration_id=sample_registration.id,
            order_id=f'REG-{sample_registration.id}',
            mapped_status='paid',
            source='callback',
            liqpay_status='success',
        )
        db_session.add_all([txn1, txn2])
        db_session.flush()

        assert sample_registration.payment_transactions.count() == 2


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
