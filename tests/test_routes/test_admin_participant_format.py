"""Формат участі обов'язковий, коли без нього бали БПР вгадуються.

На гібридному заході бали залежать від формату (онлайн 8, офлайн 12). Без
формату і без тарифу `effective_participation_format` мовчки рахує участь
очною. 26.10.2026 так онлайн-учасник, якого менеджер завів вручну, отримав
сертифікат на 12 балів замість 8. Форма учасника в адмінці тепер не
зберігає такий рядок, доки формат не вибрано.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.registration import EventRegistration
from app.models.user import User
from tests.support.rbac import grant_role


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'pf-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    # Прибираємо за собою: інакше валиться test_api_v1_clients.
    db.session.delete(user)
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _instance(event_format):
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=uuid4().hex[:8], is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format=event_format)
    db.session.add(inst)
    db.session.commit()
    return inst


def _form(instance, **over):
    data = {
        'instance_id': str(instance.id),
        'last_name': 'Петренко', 'first_name': 'Іван', 'middle_name': '',
        'email': '', 'phone': f'+38050{uuid4().int % 10**7:07d}',
        'status': 'confirmed', 'payment_status': 'unpaid', 'paid_on': '',
        'payment_amount': '1500', 'promo_code': '',
        'participation_format': '', 'participant_type': '',
    }
    data.update(over)
    return data


def _create(client, instance, **over):
    return client.post(f'/admin/instances/{instance.id}/participants/new',
                       data=_form(instance, **over), follow_redirects=True)


def _regs(instance):
    return EventRegistration.query.filter_by(instance_id=instance.id).all()


def test_hybrid_create_without_format_is_rejected(client, admin):
    _login(client, admin)
    instance = _instance('hybrid')
    html = _create(client, instance).get_data(as_text=True)
    assert _regs(instance) == []
    assert 'оберіть формат участі' in html


def test_hybrid_create_with_format_saves_it(client, admin):
    _login(client, admin)
    instance = _instance('hybrid')
    _create(client, instance, participation_format='online')
    regs = _regs(instance)
    assert [r.participation_format for r in regs] == ['online']
    assert regs[0].due_cpd_points == instance.effective_cpd_for('online')


@pytest.mark.parametrize('event_format', ['online', 'offline'])
def test_single_format_event_does_not_ask(client, admin, event_format):
    """Формат заходу однозначний -- вгадувати нічого, поле лишається
    необов'язковим."""
    _login(client, admin)
    instance = _instance(event_format)
    _create(client, instance)
    assert len(_regs(instance)) == 1


def _hybrid_reg(tariff_format=None):
    instance = _instance('hybrid')
    user = User.create_with_password(
        f'pfu-{uuid4().hex[:6]}@test.com', 'password123', first_name='У', last_name='Ч')
    db.session.flush()
    tariff = None
    if tariff_format:
        tariff = InstanceTariff(instance_id=instance.id, name='Тариф', price=1500,
                                event_format=tariff_format)
        db.session.add(tariff)
        db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501112233',
        specialty='T', workplace='T', status='confirmed', payment_status='unpaid',
        tariff_id=tariff.id if tariff else None,
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def _edit(client, reg, **over):
    return client.post(f'/admin/registrations/{reg.id}/edit',
                       data=_form(reg.instance, **over), follow_redirects=True)


def test_hybrid_edit_without_format_or_tariff_is_rejected(client, admin):
    _login(client, admin)
    reg = _hybrid_reg()
    html = _edit(client, reg, last_name='Змінено').get_data(as_text=True)
    assert 'оберіть формат участі' in html
    db.session.expire_all()
    assert reg.user.last_name != 'Змінено'


def test_hybrid_edit_with_tariff_format_does_not_ask(client, admin):
    """Тариф уже каже, онлайн це чи офлайн, -- «За тарифом» тут чесний вибір."""
    _login(client, admin)
    reg = _hybrid_reg(tariff_format='online')
    _edit(client, reg, last_name='Змінено')
    db.session.expire_all()
    assert reg.user.last_name == 'Змінено'
    assert reg.effective_participation_format == 'online'
