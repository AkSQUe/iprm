import pytest
from datetime import datetime, timezone, timedelta

from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.payment_transaction import PaymentTransaction
from app.models.registration import EventRegistration
from app.models.trainer import Trainer
from app.models.user import User


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
def sample_course(db_session, sample_trainer):
    """Базовий курс (каталожна сутність) для db-тестів."""
    course = Course(
        title='Test Course',
        slug='test-course-db',
        is_active=True,
        trainer_id=sample_trainer.id,
        base_price=500,
    )
    db_session.add(course)
    db_session.flush()
    return course


@pytest.fixture
def sample_instance(db_session, sample_course):
    """Базове проведення курсу (CourseInstance) для db-тестів."""
    instance = CourseInstance(
        course_id=sample_course.id,
        start_date=datetime.now(timezone.utc) + timedelta(days=7),
        end_date=datetime.now(timezone.utc) + timedelta(days=7, hours=4),
        event_format='offline',
        status='published',
        price=500,
    )
    db_session.add(instance)
    db_session.flush()
    return instance


@pytest.fixture
def sample_registration(db_session, sample_user, sample_instance):
    """Базова реєстрація для db-тестів."""
    reg = EventRegistration(
        user_id=sample_user.id,
        instance_id=sample_instance.id,
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
