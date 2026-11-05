"""Адмінка: подача звіту до Центру тестування і її скасування, фільтр і
колонка «Участь», підпис «Завершено · без сертифіката»."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import bpr_report as bpr_report_service
from tests.support.rbac import grant_role

NO_CERT = 'без сертифіката'


def _user(role=None):
    user = User.create_with_password(
        f'br-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Учасник', last_name='Тестовий', email_confirmed=True)
    if role:
        grant_role(user, role)
    db.session.flush()
    return user


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


@pytest.fixture
def admin(app):
    return _user('super_admin')


def _instance(ended=True):
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=f'ab-{uuid4().hex[:6]}',
                    is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    now = datetime.now(timezone.utc)
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        start_date=now - timedelta(days=2) if ended else now + timedelta(days=5))
    db.session.add(inst)
    db.session.flush()
    return inst


def _reg(inst, status='confirmed', attended=None):
    reg = EventRegistration(
        user_id=_user().id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status=status,
        payment_status='paid', attended=attended)
    db.session.add(reg)
    db.session.flush()
    return reg


def _submit(client, inst, **data):
    return client.post(f'/admin/instances/{inst.id}/bpr-report', data=data,
                       follow_redirects=True)


def test_submit_sets_date_and_reports_moved_count(client, admin):
    inst = _instance()
    r1, r2 = _reg(inst), _reg(inst)
    pending = _reg(inst, status='pending')
    _login(client, admin)
    resp = _submit(client, inst, submitted_on='2026-11-03')
    html = resp.get_data(as_text=True)
    db.session.refresh(inst)
    assert inst.bpr_report_submitted_on == date(2026, 11, 3)
    assert inst.bpr_report_submitted_by_id == admin.id
    assert (r1.status, r2.status, pending.status) == (
        'completed', 'completed', 'pending')
    assert 'Переведено в «Завершено»: 2' in html


def test_submit_defaults_to_today_kyiv(client, admin):
    from app.admin._listing import now_kyiv
    inst = _instance()
    _login(client, admin)
    _submit(client, inst)
    db.session.refresh(inst)
    assert inst.bpr_report_submitted_on == now_kyiv().date()


def test_submit_on_future_event_is_refused_with_flash(client, admin):
    inst = _instance(ended=False)
    reg = _reg(inst)
    _login(client, admin)
    html = _submit(client, inst).get_data(as_text=True)
    db.session.refresh(inst)
    assert inst.bpr_report_submitted_on is None
    assert reg.status == 'confirmed'
    assert 'Захід ще не закінчився' in html


def test_submit_rejects_bad_date_without_changes(client, admin):
    inst = _instance()
    reg = _reg(inst)
    _login(client, admin)
    _submit(client, inst, submitted_on='не-дата')
    db.session.refresh(inst)
    assert inst.bpr_report_submitted_on is None
    assert reg.status == 'confirmed'


def test_submit_without_permission_is_forbidden(client, app):
    inst = _instance()
    _login(client, _user())
    resp = client.post(f'/admin/instances/{inst.id}/bpr-report')
    assert resp.status_code == 403
    db.session.refresh(inst)
    assert inst.bpr_report_submitted_on is None


def test_undo_is_forbidden_without_permission(client, app):
    # Подача -- сервісом: g.current_user у тестовому контексті кешується
    # першим входом, тож вхід під двома користувачами в одному тесті не працює.
    inst = _instance()
    reg = _reg(inst)
    bpr_report_service.submit_report(inst, date(2026, 11, 3), _user())
    _login(client, _user())
    assert client.post(
        f'/admin/instances/{inst.id}/bpr-report/undo').status_code == 403
    db.session.refresh(inst)
    assert inst.bpr_report_submitted_on is not None
    assert reg.status == 'completed'


def test_undo_returns_registrations_and_clears_date(client, admin):
    inst = _instance()
    reg = _reg(inst)
    _login(client, admin)
    _submit(client, inst, submitted_on='2026-11-03')
    assert reg.status == 'completed'
    html = client.post(f'/admin/instances/{inst.id}/bpr-report/undo',
                       follow_redirects=True).get_data(as_text=True)
    db.session.refresh(inst)
    assert inst.bpr_report_submitted_on is None
    assert reg.status == 'confirmed'
    assert 'Повернуто в «Підтверджено»: 1' in html


def test_edit_page_shows_block_before_and_after_submission(client, admin):
    inst = _instance()
    _login(client, admin)
    url = f'/admin/instances/{inst.id}/edit'
    before = client.get(url).get_data(as_text=True)
    assert 'Звіт до Центру тестування' in before
    assert f'/admin/instances/{inst.id}/bpr-report"' in before
    assert 'bpr-report/undo' not in before
    assert 'participation/absent-unmarked' in before

    _submit(client, inst, submitted_on='2026-11-03')
    after = client.get(url).get_data(as_text=True)
    assert '03.11.2026' in after
    assert 'bpr-report/undo' in after
    assert f'/admin/instances/{inst.id}/bpr-report"' not in after


def test_edit_page_hides_actions_on_future_event(client, admin):
    inst = _instance(ended=False)
    _login(client, admin)
    html = client.get(f'/admin/instances/{inst.id}/edit').get_data(as_text=True)
    assert 'participation/absent-unmarked' not in html
    assert f'/admin/instances/{inst.id}/bpr-report"' not in html


def _list(client, **args):
    resp = client.get('/admin/registrations', query_string=dict(scope='all', **args))
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_attendance_filter_returns_only_matching(client, admin):
    inst = _instance()
    present = _reg(inst, attended=True)
    absent = _reg(inst, attended=False)
    unmarked = _reg(inst, attended=None)
    _login(client, admin)
    email = {'present': present.user.email, 'absent': absent.user.email,
             'unmarked': unmarked.user.email}

    html = _list(client, instance_id=inst.id, attendance='absent')
    assert email['absent'] in html
    assert email['present'] not in html and email['unmarked'] not in html

    html = _list(client, instance_id=inst.id, attendance='unmarked')
    assert email['unmarked'] in html
    assert email['present'] not in html and email['absent'] not in html

    html = _list(client, instance_id=inst.id, attendance='present')
    assert email['present'] in html
    assert email['absent'] not in html


def test_row_has_participation_select_pointing_to_endpoint(client, admin):
    inst = _instance()
    reg = _reg(inst, attended=False)
    _login(client, admin)
    html = _list(client, instance_id=inst.id)
    assert f'/admin/registrations/{reg.id}/participation' in html
    assert 'data-inline-field="attendance"' in html
    assert 'data-state="absent"' in html
    assert '>Участь<' in html


def _issue_cert(reg, revoked=False):
    cert = Certificate(
        registration_id=reg.id, user_id=reg.user_id, number=f'T{uuid4().hex[:8]}',
        recipient_name='X', event_title='Y', pdf_path='x.pdf',
        revoked=revoked)
    db.session.add(cert)
    db.session.flush()


def test_completed_without_certificate_is_labeled_only_after_report(client, admin):
    inst = _instance()
    reg = _reg(inst, status='confirmed')
    _login(client, admin)
    assert NO_CERT not in _list(client, instance_id=inst.id)
    _submit(client, inst, submitted_on='2026-11-03')
    assert reg.status == 'completed'
    assert 'Завершено · ' + NO_CERT in _list(client, instance_id=inst.id)


def test_completed_with_certificate_is_not_labeled(client, admin):
    inst = _instance()
    reg = _reg(inst, status='confirmed')
    _login(client, admin)
    _submit(client, inst, submitted_on='2026-11-03')
    _issue_cert(reg)
    assert NO_CERT not in _list(client, instance_id=inst.id)
