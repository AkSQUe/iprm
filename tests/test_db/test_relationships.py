from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.payment_transaction import PaymentTransaction
from app.models.program_block import ProgramBlock
from app.models.registration import EventRegistration
from app.models.user import User


class TestCourseRelationships:
    """Зв'язки моделі Course."""

    def test_course_trainer_back_populates(self, db_session, sample_trainer):
        """Двосторонній зв'язок Course <-> Trainer."""
        course = Course(title='C', slug='c-bp-trainer', trainer_id=sample_trainer.id)
        db_session.add(course)
        db_session.flush()

        assert course.trainer.full_name == sample_trainer.full_name
        assert sample_trainer.courses.count() == 1

    def test_course_creator_back_populates(self, db_session, sample_user):
        """Двосторонній зв'язок Course.creator <-> User.created_courses."""
        course = Course(title='C', slug='c-creator', created_by=sample_user.id)
        db_session.add(course)
        db_session.flush()

        assert course.creator.email == sample_user.email
        assert len(sample_user.created_courses) == 1
        assert sample_user.created_courses[0].slug == 'c-creator'

    def test_course_cascade_deletes_program_blocks(self, db_session):
        """CASCADE: видалення course видаляє пов'язані program_blocks."""
        course = Course(title='C', slug='c-cascade-pb')
        db_session.add(course)
        db_session.flush()

        block = ProgramBlock(course_id=course.id, heading='B', items=['i1'])
        db_session.add(block)
        db_session.flush()

        block_id = block.id
        db_session.delete(course)
        db_session.flush()

        assert db_session.get(ProgramBlock, block_id) is None

    def test_course_cascade_deletes_instances(self, db_session):
        """CASCADE: видалення course видаляє всі CourseInstance."""
        course = Course(title='C', slug='c-cascade-inst')
        db_session.add(course)
        db_session.flush()

        inst = CourseInstance(course_id=course.id, status='draft')
        db_session.add(inst)
        db_session.flush()

        inst_id = inst.id
        db_session.delete(course)
        db_session.flush()

        assert db_session.get(CourseInstance, inst_id) is None


class TestCourseInstanceRelationships:
    """Зв'язки моделі CourseInstance."""

    def test_instance_registrations_back_populates(self, db_session, sample_user, sample_instance):
        """Двосторонній зв'язок CourseInstance <-> EventRegistration."""
        reg = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
            phone='+380', specialty='S', workplace='W',
        )
        db_session.add(reg)
        db_session.flush()

        assert sample_instance.registrations.count() == 1
        assert reg.instance.id == sample_instance.id


class TestTrainerRelationships:
    """Зв'язки моделі Trainer."""

    def test_trainer_courses_dynamic(self, db_session, sample_trainer):
        """Trainer.courses -- dynamic relationship з фільтрацією."""
        c1 = Course(title='Active', slug='c-t-active', trainer_id=sample_trainer.id, is_active=True)
        c2 = Course(title='Inactive', slug='c-t-inactive', trainer_id=sample_trainer.id, is_active=False)
        db_session.add_all([c1, c2])
        db_session.flush()

        assert sample_trainer.courses.count() >= 2
        assert sample_trainer.courses.filter_by(is_active=True).count() >= 1


class TestRegistrationRelationships:
    """Зв'язки моделі EventRegistration."""

    def test_registration_user_back_populates(self, db_session, sample_user, sample_instance):
        """Двосторонній зв'язок EventRegistration <-> User."""
        reg = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
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

    def test_transaction_cascade_on_registration_delete(self, db_session, sample_user, sample_instance):
        """CASCADE: FK ondelete='CASCADE' налаштовано на payment_transactions.registration_id."""
        reg = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
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

    def test_program_block_course_back_populates(self, db_session):
        """Двосторонній зв'язок ProgramBlock <-> Course."""
        course = Course(title='Parent', slug='c-pb-bp')
        db_session.add(course)
        db_session.flush()

        block = ProgramBlock(course_id=course.id, heading='B', items=[])
        db_session.add(block)
        db_session.flush()

        assert block.course.title == 'Parent'
        assert len(course.program_blocks) == 1

    def test_program_block_ordering(self, db_session):
        """Блоки програми сортуються за sort_order."""
        course = Course(title='C', slug='c-pb-sort')
        db_session.add(course)
        db_session.flush()

        b1 = ProgramBlock(course_id=course.id, heading='Second', items=[], sort_order=2)
        b2 = ProgramBlock(course_id=course.id, heading='First', items=[], sort_order=1)
        db_session.add_all([b1, b2])
        db_session.flush()

        blocks = course.program_blocks
        assert blocks[0].heading == 'First'
        assert blocks[1].heading == 'Second'
