import pytest

from app.models.clinic import Clinic
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.payment_transaction import PaymentTransaction
from app.models.registration import EventRegistration
from app.models.trainer import Trainer
from app.models.user import User


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

    def test_course_slug_unique(self, db_session):
        """Slug курсу має бути унікальним."""
        c1 = Course(title='C1', slug='same-slug')
        db_session.add(c1)
        db_session.flush()

        c2 = Course(title='C2', slug='same-slug')
        db_session.add(c2)
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

    def test_registration_one_per_user_instance(self, db_session, sample_user, sample_instance):
        """Один користувач може зареєструватись на проведення лише раз."""
        reg1 = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
            phone='+380501234567', specialty='S', workplace='W',
        )
        db_session.add(reg1)
        db_session.flush()

        reg2 = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
            phone='+380501234567', specialty='S', workplace='W',
        )
        db_session.add(reg2)
        with pytest.raises(Exception):
            db_session.flush()


class TestDefaultValues:
    """Перевірка default values на моделях."""

    def test_course_defaults(self, db_session):
        """Курс створюється з правильними defaults."""
        course = Course(title='C', slug='c-defaults')
        db_session.add(course)
        db_session.flush()

        assert course.is_active is True
        assert course.is_featured is False
        assert course.base_price == 0

    def test_course_instance_defaults(self, db_session, sample_course):
        """CourseInstance створюється зі status='draft'."""
        inst = CourseInstance(course_id=sample_course.id)
        db_session.add(inst)
        db_session.flush()

        assert inst.status == 'draft'

    def test_user_defaults(self, db_session):
        """Користувач створюється з правильними defaults."""
        user = User(email='def@test.com', password='pass1234')
        db_session.add(user)
        db_session.flush()

        assert user.is_active is True
        assert user.is_admin is False

    def test_registration_defaults(self, db_session, sample_user, sample_instance):
        """Реєстрація створюється з правильними defaults."""
        reg = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
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

    def test_course_max_participants_zero_rejected(self, db_session):
        """CHECK constraint: max_participants не може бути 0."""
        course = Course(title='C', slug='c-ck-mp-zero', max_participants=0)
        db_session.add(course)
        with pytest.raises(Exception):
            db_session.flush()

    def test_course_max_participants_negative_rejected(self, db_session):
        """CHECK constraint: max_participants не може бути від'ємним."""
        course = Course(title='C', slug='c-ck-mp-neg', max_participants=-1)
        db_session.add(course)
        with pytest.raises(Exception):
            db_session.flush()

    def test_course_max_participants_null_allowed(self, db_session):
        """max_participants NULL допустимий (необмежена кількість)."""
        course = Course(title='C', slug='c-ck-mp-null', max_participants=None)
        db_session.add(course)
        db_session.flush()
        assert course.max_participants is None

    def test_course_max_participants_positive_allowed(self, db_session):
        """max_participants >= 1 допустимий."""
        course = Course(title='C', slug='c-ck-mp-pos', max_participants=30)
        db_session.add(course)
        db_session.flush()
        assert course.max_participants == 30

    def test_course_cpd_points_negative_rejected(self, db_session):
        """CHECK constraint: cpd_points не може бути від'ємним."""
        course = Course(title='C', slug='c-ck-cpd-neg', cpd_points=-1)
        db_session.add(course)
        with pytest.raises(Exception):
            db_session.flush()

    def test_course_cpd_points_zero_allowed(self, db_session):
        """cpd_points = 0 допустимий."""
        course = Course(title='C', slug='c-ck-cpd-zero', cpd_points=0)
        db_session.add(course)
        db_session.flush()
        assert course.cpd_points == 0

    def test_course_cpd_points_null_allowed(self, db_session):
        """cpd_points NULL допустимий."""
        course = Course(title='C', slug='c-ck-cpd-null', cpd_points=None)
        db_session.add(course)
        db_session.flush()
        assert course.cpd_points is None

    def test_course_base_price_negative_rejected(self, db_session):
        """CHECK constraint: base_price не може бути від'ємним."""
        course = Course(title='C', slug='c-ck-bp-neg', base_price=-100)
        db_session.add(course)
        with pytest.raises(Exception):
            db_session.flush()

    def test_instance_status_invalid_rejected(self, db_session, sample_course):
        """CHECK constraint: status тільки з дозволеного списку."""
        inst = CourseInstance(course_id=sample_course.id, status='invalid_status')
        db_session.add(inst)
        with pytest.raises(Exception):
            db_session.flush()

    def test_instance_format_invalid_rejected(self, db_session, sample_course):
        """CHECK constraint: event_format тільки з дозволеного списку."""
        inst = CourseInstance(
            course_id=sample_course.id, status='draft', event_format='teleport',
        )
        db_session.add(inst)
        with pytest.raises(Exception):
            db_session.flush()

    def test_registration_cpd_awarded_negative_rejected(self, db_session, sample_user, sample_instance):
        """CHECK constraint: cpd_points_awarded не може бути від'ємним."""
        reg = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
            phone='+380', specialty='S', workplace='W',
            cpd_points_awarded=-5,
        )
        db_session.add(reg)
        with pytest.raises(Exception):
            db_session.flush()

    def test_registration_payment_amount_negative_rejected(self, db_session, sample_user, sample_instance):
        """CHECK constraint: payment_amount не може бути від'ємним."""
        reg = EventRegistration(
            user_id=sample_user.id, instance_id=sample_instance.id,
            phone='+380', specialty='S', workplace='W',
            payment_amount=-100,
        )
        db_session.add(reg)
        with pytest.raises(Exception):
            db_session.flush()


class TestPaymentTransactionConstraints:
    """Перевірка CHECK constraints на PaymentTransaction."""

    def test_source_valid_values(self, db_session, sample_registration):
        """CHECK constraint: source тільки з дозволеного списку."""
        txn = PaymentTransaction(
            registration_id=sample_registration.id,
            order_id=f'REG-{sample_registration.id}',
            mapped_status='paid',
            source='callback',
        )
        db_session.add(txn)
        db_session.flush()
        assert txn.id is not None

    def test_source_invalid_rejected(self, db_session, sample_registration):
        """CHECK constraint: невалідний source відхиляється."""
        txn = PaymentTransaction(
            registration_id=sample_registration.id,
            order_id=f'REG-{sample_registration.id}',
            mapped_status='paid',
            source='invalid_source',
        )
        db_session.add(txn)
        with pytest.raises(Exception):
            db_session.flush()

    def test_mapped_status_valid_values(self, db_session, sample_registration):
        """CHECK constraint: mapped_status тільки з дозволеного списку."""
        for status in ('unpaid', 'pending', 'paid', 'refunded'):
            db_session.rollback()
            txn = PaymentTransaction(
                registration_id=sample_registration.id,
                order_id=f'REG-{sample_registration.id}',
                mapped_status=status,
                source='manual',
            )
            db_session.add(txn)
            db_session.flush()
            assert txn.id is not None

    def test_mapped_status_invalid_rejected(self, db_session, sample_registration):
        """CHECK constraint: невалідний mapped_status відхиляється."""
        txn = PaymentTransaction(
            registration_id=sample_registration.id,
            order_id=f'REG-{sample_registration.id}',
            mapped_status='invalid',
            source='callback',
        )
        db_session.add(txn)
        with pytest.raises(Exception):
            db_session.flush()

    def test_payment_transaction_defaults(self, db_session, sample_registration):
        """PaymentTransaction створюється з timestamps."""
        txn = PaymentTransaction(
            registration_id=sample_registration.id,
            order_id=f'REG-{sample_registration.id}',
            mapped_status='paid',
            source='callback',
        )
        db_session.add(txn)
        db_session.flush()

        assert txn.created_at is not None
        assert txn.updated_at is not None


class TestTimestamps:
    """Перевірка автоматичних timestamps."""

    def test_user_timestamps(self, db_session):
        """created_at та updated_at заповнюються автоматично."""
        user = User(email='ts@test.com', password='pass1234')
        db_session.add(user)
        db_session.flush()

        assert user.created_at is not None
        assert user.updated_at is not None

    def test_course_timestamps(self, db_session):
        """created_at та updated_at заповнюються автоматично."""
        course = Course(title='C', slug='c-ts')
        db_session.add(course)
        db_session.flush()

        assert course.created_at is not None
        assert course.updated_at is not None
