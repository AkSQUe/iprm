import pytest
from app.models.user import User
from app.models.event import Event
from app.models.registration import EventRegistration


def test_registration_creation(db_session):
    """Створення реєстрації."""
    user = User(email='reg@test.com', password='pass1234')
    event = Event(title='E', slug='e-reg')
    db_session.add_all([user, event])
    db_session.flush()

    reg = EventRegistration(
        user_id=user.id,
        event_id=event.id,
        phone='+380501234567',
        specialty='Dentist',
        workplace='Clinic X',
    )
    db_session.add(reg)
    db_session.flush()

    assert reg.id is not None
    assert reg.status == 'pending'
    assert reg.payment_status == 'unpaid'
    assert reg.status_label == 'Очікує'
    assert reg.payment_status_label == 'Не оплачено'


def test_registration_unique_constraint(db_session):
    """Один користувач -- одна реєстрація на захід."""
    user = User(email='dup@test.com', password='pass1234')
    event = Event(title='E', slug='e-dup')
    db_session.add_all([user, event])
    db_session.flush()

    reg1 = EventRegistration(
        user_id=user.id, event_id=event.id,
        phone='+380', specialty='S', workplace='W',
    )
    db_session.add(reg1)
    db_session.flush()

    reg2 = EventRegistration(
        user_id=user.id, event_id=event.id,
        phone='+380', specialty='S', workplace='W',
    )
    db_session.add(reg2)
    with pytest.raises(Exception):
        db_session.flush()


def test_registration_relationships(db_session):
    """Зв'язки user та event."""
    user = User(email='rel@test.com', password='pass1234')
    event = Event(title='E', slug='e-rel')
    db_session.add_all([user, event])
    db_session.flush()

    reg = EventRegistration(
        user_id=user.id, event_id=event.id,
        phone='+380', specialty='S', workplace='W',
    )
    db_session.add(reg)
    db_session.flush()

    assert reg.user.email == 'rel@test.com'
    assert reg.event.title == 'E'
