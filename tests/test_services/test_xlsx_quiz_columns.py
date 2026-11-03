"""Колонки тестування у xlsx-вивантаженнях учасників і реєстрацій.

Менеджер формує звіт по заходу з Excel, а часу проходження тесту там не
було -- лише бейдж на сторінці. Обидва файли беруть значення з одного
помічника (quiz_report_values), тож і перевіряються однаково.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from openpyxl import load_workbook

from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.medical_profile import MedicalProfile
from app.models.quiz_attempt import QuizAttempt
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import quiz_service, xlsx_io, xlsx_reports

EMAIL_PREFIX = 'xq-'
L = xlsx_io.QUIZ_REPORT_LABELS
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)  # 12:00 за Києвом


@pytest.fixture(autouse=True)
def clean(app):
    """Прибрати своїх користувачів: тестова БД спільна на сесію, а
    /api/v1/participants у чужому тесті бачить лише 200 рядків."""
    def _wipe():
        stale = [u.id for u in User.query.filter(
            User.email.like(f'{EMAIL_PREFIX}%@test.com')).all()]
        if stale:
            QuizAttempt.query.filter(QuizAttempt.user_id.in_(stale)).delete(
                synchronize_session=False)
            EventRegistration.query.filter(
                EventRegistration.user_id.in_(stale)).delete(
                synchronize_session=False)
            for model in (AuthIdentity, MedicalProfile):
                model.query.filter(model.user_id.in_(stale)).delete(
                    synchronize_session=False)
            User.query.filter(User.id.in_(stale)).delete(
                synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


def _instance():
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=f'xq-{uuid4().hex[:6]}',
                    is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=T0 - timedelta(days=1),
    )
    db.session.add(inst)
    db.session.commit()
    return inst


def _registration(inst):
    user = User.create_with_password(
        f'{EMAIL_PREFIX}{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий')
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501112233',
        specialty='Дерматолог', workplace='Клініка',
        status='confirmed', payment_status='paid',
    )
    db.session.add(reg)
    db.session.flush()
    return reg


def _attempt(reg, number, minutes=None, score=None, passed=False, start=T0):
    attempt = QuizAttempt(
        registration_id=reg.id, user_id=reg.user_id, attempt_number=number,
        question_ids=[], answer_order={}, submitted_answers={},
        total=10, passing_score=8, started_at=start,
        submitted_at=(start + timedelta(minutes=minutes)) if minutes is not None else None,
        score=score, passed=passed,
    )
    db.session.add(attempt)
    db.session.flush()
    if passed and reg.quiz_passed_at is None:
        reg.quiz_passed_at = attempt.submitted_at
    return attempt


def _rows(xlsx_bytes, sheet):
    ws = load_workbook(xlsx_bytes)[sheet]
    header = [c.value for c in ws[1]]
    return [dict(zip(header, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]


# --- вибір спроби ---------------------------------------------------------

def test_report_attempt_prefers_first_passed_then_last_finished(app):
    inst = _instance()
    reg = _registration(inst)
    a1 = _attempt(reg, 1, minutes=10, score=5)
    a2 = _attempt(reg, 2, minutes=12, score=9, passed=True,
                  start=T0 + timedelta(hours=1))
    a3 = _attempt(reg, 3, minutes=8, score=10, passed=True,
                  start=T0 + timedelta(hours=2))
    # Порядок у списку не має значення: вирішує attempt_number.
    assert quiz_service.report_attempt([a3, a1, a2]) is a2
    assert quiz_service.report_attempt([a1]) is a1
    assert quiz_service.report_attempt([]) is None


def test_report_attempt_in_progress_only(app):
    inst = _instance()
    reg = _registration(inst)
    open_attempt = _attempt(reg, 1)
    assert quiz_service.report_attempt([open_attempt]) is open_attempt


# --- значення колонок -----------------------------------------------------

def test_values_for_passed_participant(app):
    inst = _instance()
    reg = _registration(inst)
    _attempt(reg, 1, minutes=10, score=5)
    _attempt(reg, 2, minutes=25, score=9, passed=True,
             start=T0 + timedelta(days=1))
    db.session.commit()

    result, score, attempts, started, submitted, duration = (
        xlsx_io.quiz_report_values(reg))
    assert result == 'Склав'
    assert score == '9/10'
    assert attempts == 2
    # Київський час без TZ -- так його читає Excel.
    assert started == datetime(2026, 10, 21, 12, 0)
    assert submitted == datetime(2026, 10, 21, 12, 25)
    assert duration == 25


def test_values_for_failed_and_in_progress_and_untouched(app):
    inst = _instance()
    failed = _registration(inst)
    _attempt(failed, 1, minutes=7, score=4)
    in_progress = _registration(inst)
    _attempt(in_progress, 1)
    untouched = _registration(inst)
    db.session.commit()

    assert xlsx_io.quiz_report_values(failed)[:3] == ['Не склав', '4/10', 1]

    result, score, attempts, started, submitted, duration = (
        xlsx_io.quiz_report_values(in_progress))
    assert (result, score, attempts) == ('Проходить', '', None)
    assert started == datetime(2026, 10, 20, 12, 0)
    assert submitted is None and duration is None

    assert xlsx_io.quiz_report_values(untouched) == [''] + [None] * 5


def test_sub_minute_attempt_is_not_zero_minutes(app):
    inst = _instance()
    reg = _registration(inst)
    attempt = _attempt(reg, 1, minutes=0, score=9, passed=True)
    attempt.submitted_at = attempt.started_at + timedelta(seconds=40)
    db.session.commit()
    assert xlsx_io.quiz_report_values(reg)[-1] == 1


# --- обидва файли ---------------------------------------------------------

def test_participants_export_has_quiz_columns(app):
    inst = _instance()
    reg = _registration(inst)
    _attempt(reg, 1, minutes=15, score=8, passed=True)
    db.session.commit()

    rows = _rows(xlsx_io.export_participants_xlsx(instance_id=inst.id), 'Учасники')
    assert len(rows) == 1
    row = rows[0]
    assert row[L['quiz_result']] == 'Склав'
    assert row[L['quiz_score']] == '8/10'
    assert row[L['quiz_started_at']] == datetime(2026, 10, 20, 12, 0)
    assert row[L['quiz_submitted_at']] == datetime(2026, 10, 20, 12, 15)
    assert row[L['quiz_duration_min']] == 15


def test_blank_participants_template_has_no_quiz_columns(app):
    """Шаблон для заповнення -- лише редаговані колонки: колонка тесту там
    була б пасткою (заповнив -- нічого не сталось)."""
    ws = load_workbook(xlsx_io.export_participants_xlsx(blank=True))['Учасники']
    header = {c.value for c in ws[1]}
    assert not header & set(L.values())


def test_registrations_report_has_quiz_columns(app):
    inst = _instance()
    reg = _registration(inst)
    _attempt(reg, 1, minutes=30, score=6)
    db.session.commit()

    rows = _rows(xlsx_reports.export_registrations_xlsx([reg]), 'Реєстрації')
    row = rows[0]
    assert row[L['quiz_result']] == 'Не склав'
    assert row[L['quiz_attempts']] == 1
    assert row[L['quiz_duration_min']] == 30
    # Колонка дати реєстрації лишилась останньою -- тест не зсунув її.
    assert list(row)[-1] == 'Дата реєстрації'


def test_participants_export_reimports_without_quiz_columns_noise(app, tmp_path):
    """Вивантажений файл із колонками тесту імпортується назад: невідомі для
    імпорту заголовки ігноруються, і жодна з них не потрапляє в зміни."""
    inst = _instance()
    reg = _registration(inst)
    _attempt(reg, 1, minutes=15, score=8, passed=True)
    db.session.commit()

    path = tmp_path / 'roundtrip.xlsx'
    path.write_bytes(xlsx_io.export_participants_xlsx(instance_id=inst.id).getvalue())
    plan = xlsx_io.parse_participants_xlsx(path)
    assert plan.is_valid, plan.errors
    assert [c.action for c in plan.changes] != ['error']
    changed = {f for c in plan.changes for f in c.fields_changed}
    assert not changed & {v.lower() for v in L.values()}
