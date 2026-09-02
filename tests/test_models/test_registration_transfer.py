"""Обмеження таблиці registration_transfers.

Перевіряємо рівень БД, а не Python: правило "організатор не може вимагати
доплату" родом з опублікованої Політики (§3.2), і форма -- не те місце, де
його можна обійти наступною правкою шаблону.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.registration_transfer import RegistrationTransfer
from app.models.user import User
from tests.refund_fixtures import purge

PREFIX = 'rtm-'


@pytest.fixture
def reg(app):
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    db.session.flush()  # призначає user.id -- set_password() вимагає persisted user
    user.set_password('x' * 12)
    src = CourseInstance(course_id=course.id, status='published')
    dst = CourseInstance(course_id=course.id, status='published')
    db.session.add_all([src, dst])
    db.session.flush()
    item = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(item)
    db.session.commit()
    yield item, src, dst
    purge(PREFIX, slug_prefix=PREFIX)


def _transfer(item, src, dst, **kwargs):
    data = dict(
        registration_id=item.id, from_instance_id=src.id, to_instance_id=dst.id,
        initiator='participant', tariff_decision='keep',
        state=RegistrationTransfer.STATE_APPLIED,
    )
    data.update(kwargs)
    return RegistrationTransfer(**data)


def test_organizer_cannot_demand_surcharge(reg):
    """CHECK §3.2: перенесення з нашої ініціативи -- без додаткової оплати."""
    item, src, dst = reg
    db.session.add(_transfer(item, src, dst,
                             initiator='organizer', tariff_decision='surcharge'))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_participant_may_be_asked_to_surcharge(reg):
    item, src, dst = reg
    db.session.add(_transfer(item, src, dst,
                             initiator='participant', tariff_decision='surcharge'))
    db.session.commit()
    assert RegistrationTransfer.query.count() == 1


def test_only_one_open_transfer_per_registration(reg):
    """Партіальний унікальний індекс: два відкритих переноси на одну
    реєстрацію означали б, що згода закриває випадковий із них."""
    item, src, dst = reg
    db.session.add(_transfer(item, src, dst,
                             state=RegistrationTransfer.STATE_AWAITING))
    db.session.commit()
    db.session.add(_transfer(item, src, dst,
                             state=RegistrationTransfer.STATE_AWAITING))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_closed_transfers_do_not_collide(reg):
    """Індекс частковий: закриті переноси не заважають наступному."""
    item, src, dst = reg
    db.session.add(_transfer(item, src, dst,
                             state=RegistrationTransfer.STATE_ACCEPTED))
    db.session.add(_transfer(item, src, dst,
                             state=RegistrationTransfer.STATE_ACCEPTED))
    db.session.commit()
    assert RegistrationTransfer.query.count() == 2


def test_surcharge_due_only_until_paid(reg):
    item, src, dst = reg
    row = _transfer(item, src, dst, tariff_decision='surcharge', difference=500)
    db.session.add(row)
    db.session.commit()
    assert row.surcharge_due is True
    row.surcharge_paid_at = db.func.now()
    db.session.commit()
    assert row.surcharge_due is False


def test_consent_token_expires(reg):
    item, src, dst = reg
    row = _transfer(item, src, dst)
    token = row.issue_consent_token(ttl_days=30)
    assert len(token) > 20
    assert row.consent_token_active is True
    row.consent_token_expires_at = None
    assert row.consent_token_active is False
