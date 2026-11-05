"""Форма учасника: поле «Участь» має три стани і пишеться як є."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from tests.support.rbac import grant_role


@pytest.fixture
def admin_client(app, client):
    user = User.create_with_password(
        f'pa-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    yield client
    db.session.delete(user)
    db.session.commit()


def _instance():
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=uuid4().hex[:8], is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='published', event_format='offline')
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


@pytest.mark.parametrize('choice, expected', [
    ('unmarked', None), ('present', True), ('absent', False),
])
def test_create_writes_exactly_chosen_state(admin_client, choice, expected):
    inst = _instance()
    admin_client.post(f'/admin/instances/{inst.id}/participants/new',
                      data=_form(inst, attended=choice), follow_redirects=True)
    regs = EventRegistration.query.filter_by(instance_id=inst.id).all()
    assert [r.attended for r in regs] == [expected]


def test_edit_form_preselects_current_state_and_keeps_unmarked(admin_client):
    inst = _instance()
    admin_client.post(f'/admin/instances/{inst.id}/participants/new',
                      data=_form(inst), follow_redirects=True)
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.attended is None
    for attended, selected in ((None, 'unmarked'), (True, 'present'), (False, 'absent')):
        reg.attended = attended
        db.session.commit()
        html = admin_client.get(f'/admin/registrations/{reg.id}/edit').get_data(as_text=True)
        assert f'<option selected value="{selected}">' in html
