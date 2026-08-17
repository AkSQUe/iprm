"""Колонки «Анкета», «Тестування», «Сертифікат» у реєстраціях проведення.

Менеджер вирішує за цією таблицею, кому нагадати про анкету і кому вже можна
видавати сертифікат. Раніше бейдж «Анкета не заповнена» тулився в клітинці з
іменем учасника: його було погано видно й неможливо порівняти рядки очима.

Стан тестування береться батчем (`eligibility_map`), тож окремо перевіряємо, що
таблиця не дорожчає з кількістю учасників -- груп по 20-30 осіб тут звичайна річ.
"""
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_quiz import CourseQuiz, QuizQuestion
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import certificate_service, quiz_service

_event_numbers = count(7000000)

FULL_PROFILE = {
    'participant_type': 'doctor', 'middle_name': 'Іванович',
    'birth_date': datetime(1985, 3, 12).date(), 'education': '2010, НМУ',
    'workplace': 'Клініка', 'position': 'лікар', 'specializations': ['therapy'],
}


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'ac-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True)
    db.session.flush()
    return u


@pytest.fixture(autouse=True)
def bpr_ready(app):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    settings.bpr_participant_counter = 0
    db.session.flush()
    return settings


@pytest.fixture
def no_pdf(monkeypatch):
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _instance(with_quiz=True, bank=10, started=True, event_num=None):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'rc-{uuid4().hex[:6]}',
        is_active=True, event_type='course', cpd_points=12,
        bpr_event_number=(event_num if event_num is not None
                          else str(next(_event_numbers))),
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        start_date=(datetime.now(timezone.utc) - timedelta(days=1) if started
                    else datetime.now(timezone.utc) + timedelta(days=7)))
    db.session.add(inst)
    db.session.flush()
    if with_quiz:
        quiz = CourseQuiz(course_id=course.id, questions_per_attempt=10,
                          passing_score=8, is_active=True, shuffle_answers=False)
        db.session.add(quiz)
        db.session.flush()
        for i in range(bank):
            db.session.add(QuizQuestion(
                quiz_id=quiz.id, text=f'П {i + 1}?', sort_order=i,
                answers=[{'text': f'В {j}', 'is_correct': j == 0} for j in range(4)]))
        db.session.flush()
    return inst


def _registration(inst, profile=True, paid=True, status='confirmed'):
    user = User.create_with_password(
        f'r-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Учасник', last_name='Тестовий', email_confirmed=True)
    db.session.flush()
    if profile:
        prof = user.medical_profile or MedicalProfile(user_id=user.id)
        for field, value in FULL_PROFILE.items():
            setattr(prof, field, value)
        user.medical_profile = prof
        db.session.add(prof)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status=status,
        payment_status='paid' if paid else 'unpaid')
    db.session.add(reg)
    db.session.flush()
    return reg


def _html(client, inst):
    resp = client.get(f'/admin/instances/{inst.id}/registrations')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


# ---- заголовки --------------------------------------------------------------

def test_columns_are_present(client, admin):
    inst = _instance()
    _registration(inst)
    _login(client, admin)
    html = _html(client, inst)
    for header in ('>Анкета<', '>Тестування<', '>Сертифікат<'):
        assert header in html, header


def test_profile_badge_left_the_participant_cell(client, admin):
    """Бейдж мусить бути у власній колонці, а не в клітинці з іменем."""
    inst = _instance()
    reg = _registration(inst, profile=False)
    _login(client, admin)
    html = _html(client, inst)

    name_cell = html.split(reg.user.email)[0].rsplit('<td>', 1)[-1]
    assert 'Не заповнена' not in name_cell
    assert 'Не заповнена' in html


# ---- колонка «Анкета» -------------------------------------------------------

def test_complete_profile_shown_as_filled(client, admin):
    inst = _instance()
    _registration(inst)
    _login(client, admin)
    assert 'Заповнена' in _html(client, inst)


def test_incomplete_profile_lists_missing_fields(client, admin):
    """Менеджеру треба знати, чого саме бракує, щоб сказати це учаснику."""
    inst = _instance()
    reg = _registration(inst)
    reg.user.medical_profile.workplace = None
    db.session.flush()
    _login(client, admin)
    html = _html(client, inst)
    assert 'Не заповнена' in html
    assert 'Місце роботи' in html


# ---- колонка «Тестування» ---------------------------------------------------

def test_no_quiz_shows_dash(client, admin):
    inst = _instance(with_quiz=False)
    _registration(inst)
    _login(client, admin)
    html = _html(client, inst)
    assert 'Не починав' not in html


def test_waiting_for_profile(client, admin):
    inst = _instance()
    _registration(inst, profile=False)
    _login(client, admin)
    assert 'Чекає анкету' in _html(client, inst)


def test_waiting_for_payment(client, admin):
    inst = _instance()
    _registration(inst, paid=False)
    _login(client, admin)
    assert 'Чекає оплату' in _html(client, inst)


def test_event_not_started(client, admin):
    inst = _instance(started=False)
    _registration(inst)
    _login(client, admin)
    assert 'Захід не почався' in _html(client, inst)


def test_missing_bpr_data_is_flagged(client, admin):
    """Найдорожчий стан: тест не відкриється нікому, і причина -- у курсі."""
    inst = _instance(event_num='')
    _registration(inst)
    _login(client, admin)
    assert 'Немає даних БПР' in _html(client, inst)


def test_not_started_yet_by_participant(client, admin):
    inst = _instance()
    _registration(inst)
    _login(client, admin)
    assert 'Не починав' in _html(client, inst)


def test_in_progress(client, admin):
    inst = _instance()
    reg = _registration(inst)
    quiz_service.start_attempt(reg)
    db.session.flush()
    _login(client, admin)
    assert 'Проходить' in _html(client, inst)


def test_passed_shows_score_and_attempts(client, admin, no_pdf):
    inst = _instance()
    reg = _registration(inst)
    attempt = quiz_service.start_attempt(reg)
    for qid in attempt.question_ids:
        question = db.session.get(QuizQuestion, qid)
        order = attempt.ordered_answer_indexes(qid)
        quiz_service.record_answer(attempt, qid, order.index(question.correct_index))
    quiz_service.submit_attempt(attempt)

    _login(client, admin)
    html = _html(client, inst)
    assert 'Склав' in html
    assert '10/10' in html
    assert 'спроб: 1' in html


def test_attempts_exhausted(client, admin, no_pdf):
    inst = _instance()
    quiz = CourseQuiz.query.filter_by(course_id=inst.course_id).one()
    quiz.max_attempts = 1
    db.session.flush()
    reg = _registration(inst)

    # Завершуємо без жодної відповіді -- 0 з 10, спроба єдина і витрачена.
    quiz_service.submit_attempt(quiz_service.start_attempt(reg))

    _login(client, admin)
    assert 'Спроби вичерпано' in _html(client, inst)


def test_cancelled_registration_has_no_quiz_state(client, admin):
    inst = _instance()
    _registration(inst, status='cancelled')
    _login(client, admin)
    html = _html(client, inst)
    assert 'Не починав' not in html


# ---- колонка «Сертифікат» ---------------------------------------------------

def test_certificate_not_issued(client, admin):
    inst = _instance()
    _registration(inst)
    _login(client, admin)
    assert 'Не видано' in _html(client, inst)


def test_issued_certificate_shows_number_and_link(client, admin, no_pdf):
    inst = _instance()
    reg = _registration(inst)
    cert = certificate_service.issue_certificate(reg)

    _login(client, admin)
    html = _html(client, inst)
    assert cert.number in html
    assert f'/admin/registrations/{reg.id}/certificate/download' in html
    assert '12 балів' in html


def test_revoked_certificate_is_marked(client, admin, no_pdf):
    inst = _instance()
    reg = _registration(inst)
    cert = certificate_service.issue_certificate(reg)
    cert.revoked = True
    db.session.flush()

    _login(client, admin)
    html = _html(client, inst)
    assert 'Відкликано' in html


# ---- перф-інваріант ---------------------------------------------------------

def test_page_does_not_grow_with_participants(client, admin):
    """Групи по 20-30 осіб тут звичайна річ, тож стан тестування -- батчем."""
    from sqlalchemy import event

    _login(client, admin)

    def _count(inst):
        seen = []

        def _tap(_c, _cur, statement, _p, _ctx, _m):
            if statement.lstrip().upper().startswith('SELECT'):
                seen.append(statement)

        event.listen(db.engine, 'before_cursor_execute', _tap)
        try:
            _html(client, inst)
        finally:
            event.remove(db.engine, 'before_cursor_execute', _tap)
        return len(seen)

    # Саме flush, а не commit: запит тест-клієнта ходить тією ж сесією, тож
    # незакомічені рядки він бачить. Коміт лишав би по собі користувачів, які
    # переживають відкат фікстури, і чужі тести з посторінковою видачею
    # (api/v1/participants?per_page=200) починали б не знаходити своїх.
    small = _instance()
    for _ in range(2):
        _registration(small)
    db.session.flush()
    few = _count(small)

    big = _instance()
    for _ in range(12):
        _registration(big)
    db.session.flush()
    many = _count(big)

    assert many - few <= 4, (
        f'12 учасників замість 2 дали +{many - few} SELECT ({few} -> {many}) -- '
        f'схоже, стан тестування рахується поштучно'
    )


# ---- детальний розбір по учаснику -------------------------------------------

def _detail(client, reg):
    resp = client.get(f'/admin/registrations/{reg.id}/quiz')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _answer(attempt, correct_count):
    """Відповісти на всі питання; перші `correct_count` -- правильно."""
    for i, qid in enumerate(attempt.question_ids):
        question = db.session.get(QuizQuestion, qid)
        order = attempt.ordered_answer_indexes(qid)
        right = order.index(question.correct_index)
        wrong = next(p for p in range(len(order)) if p != right)
        quiz_service.record_answer(attempt, qid, right if i < correct_count else wrong)
    db.session.flush()


def test_status_links_to_detail(client, admin):
    inst = _instance()
    reg = _registration(inst)
    _login(client, admin)
    assert f'/admin/registrations/{reg.id}/quiz' in _html(client, inst)


def test_detail_shows_every_question_with_both_answers(client, admin, no_pdf):
    """Головне: видно, ЩО обрав учасник і що було правильним."""
    inst = _instance()
    reg = _registration(inst)
    attempt = quiz_service.start_attempt(reg)
    _answer(attempt, 6)
    quiz_service.submit_attempt(attempt)

    _login(client, admin)
    html = _detail(client, reg)

    assert 'Спроба 1' in html
    assert '6/10' in html
    assert 'Відповідь учасника' in html
    assert 'Правильна відповідь' in html
    # Усі десять питань у розборі.
    for i in range(1, 11):
        assert f'П {i}?' in html


def test_detail_marks_wrong_rows(client, admin, no_pdf):
    inst = _instance()
    reg = _registration(inst)
    attempt = quiz_service.start_attempt(reg)
    _answer(attempt, 6)
    quiz_service.submit_attempt(attempt)

    _login(client, admin)
    html = _detail(client, reg)
    # Чотири незараховані рядки підсвічені.
    assert html.count('admin-quiz-report__row--wrong') == 4


def test_detail_shows_unanswered_questions(client, admin, no_pdf):
    inst = _instance()
    reg = _registration(inst)
    attempt = quiz_service.start_attempt(reg)
    _answer(attempt, 3)
    answers = dict(attempt.submitted_answers)
    for qid in attempt.question_ids[5:]:
        answers.pop(str(qid), None)
    attempt.submitted_answers = answers
    db.session.flush()
    quiz_service.submit_attempt(attempt)

    _login(client, admin)
    assert 'без відповіді' in _detail(client, reg)


def test_detail_shows_all_attempts_newest_first(client, admin, no_pdf):
    inst = _instance()
    quiz = CourseQuiz.query.filter_by(course_id=inst.course_id).one()
    quiz.max_attempts = 3
    db.session.flush()
    reg = _registration(inst)

    for correct in (2, 5):
        attempt = quiz_service.start_attempt(reg)
        _answer(attempt, correct)
        quiz_service.submit_attempt(attempt)

    _login(client, admin)
    html = _detail(client, reg)
    assert html.index('Спроба 2') < html.index('Спроба 1')
    assert '5/10' in html and '2/10' in html


def test_detail_explains_why_test_is_closed(client, admin):
    """«Не склав» і «не міг почати» -- різні речі, і це має бути видно."""
    inst = _instance()
    reg = _registration(inst, profile=False)
    _login(client, admin)
    html = _detail(client, reg)
    assert 'анкета МОЗ №725 не заповнена' in html
    assert 'По батькові' in html


def test_detail_shows_threshold_and_attempts_left(client, admin):
    inst = _instance()
    reg = _registration(inst)
    _login(client, admin)
    html = _detail(client, reg)
    assert '8/10' in html
    assert 'Спроб залишилось' in html


def test_detail_without_attempts(client, admin):
    inst = _instance()
    reg = _registration(inst)
    _login(client, admin)
    assert 'Спроб ще не було' in _detail(client, reg)


def test_detail_requires_admin(client, app):
    inst = _instance()
    reg = _registration(inst)
    db.session.commit()
    resp = client.get(f'/admin/registrations/{reg.id}/quiz')
    assert resp.status_code in (302, 401, 403)


def test_detail_missing_registration_redirects(client, admin):
    _login(client, admin)
    assert client.get('/admin/registrations/999999/quiz').status_code == 302


def test_deleted_question_is_explained_not_blank(client, admin, no_pdf):
    """Питання прибрали з банку після спроби -- рядок мусить це сказати."""
    inst = _instance()
    reg = _registration(inst)
    attempt = quiz_service.start_attempt(reg)
    _answer(attempt, 10)
    db.session.delete(db.session.get(QuizQuestion, attempt.question_ids[0]))
    db.session.flush()
    quiz_service.submit_attempt(attempt)

    _login(client, admin)
    html = _detail(client, reg)
    assert 'питання видалено з банку' in html
    assert 'не карається' in html


# ---- спільний партіал: обидві таблиці --------------------------------------
#
# Колонки живуть у макросі `_registration_progress.html`, бо потрібні і на
# сторінці одного заходу, і в загальному списку. Дві копії badge-ів (а станів
# дев'ять) розійшлися б на першій правці, тож перевіряємо обидві сторінки.

def _all_html(client):
    """Загальний список.

    `scope=all` обов'язково: за замовчуванням сторінка показує лише МАЙБУТНІ
    заходи (щоб не вивалювати тисячі реєстрацій на минулі), а тестування
    стосується саме проведених -- інакше таблиця порожня і колонок не видно.
    """
    resp = client.get('/admin/registrations?scope=all&per_page=100')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_columns_present_in_all_registrations_list(client, admin):
    inst = _instance()
    _registration(inst)
    _login(client, admin)
    html = _all_html(client)
    for header in ('>Анкета<', '>Тестування<', '>Сертифікат<'):
        assert header in html, header


def test_all_list_shows_profile_state(client, admin):
    inst = _instance()
    _registration(inst, profile=False)
    _login(client, admin)
    assert 'Не заповнена' in _all_html(client)


def test_all_list_shows_quiz_state(client, admin):
    inst = _instance()
    _registration(inst)
    _login(client, admin)
    assert 'Не починав' in _all_html(client)


def test_all_list_links_to_detail(client, admin):
    inst = _instance()
    reg = _registration(inst)
    _login(client, admin)
    assert f'/admin/registrations/{reg.id}/quiz' in _all_html(client)


def test_all_list_shows_certificate(client, admin, no_pdf):
    inst = _instance()
    reg = _registration(inst)
    cert = certificate_service.issue_certificate(reg)
    _login(client, admin)
    assert cert.number in _all_html(client)


def test_both_pages_render_same_state_wording(client, admin):
    """Один і той самий стан мусить називатися однаково на обох сторінках."""
    inst = _instance()
    _registration(inst, profile=False)
    _login(client, admin)

    per_event = _html(client, inst)
    everything = _all_html(client)
    for wording in ('Чекає анкету', 'Не заповнена', 'Не видано'):
        assert wording in per_event, f'сторінка заходу: {wording}'
        assert wording in everything, f'загальний список: {wording}'


def test_all_list_does_not_grow_with_rows(client, admin):
    """Загальний список пагінований, але стан тестування все одно батчем."""
    from sqlalchemy import event

    _login(client, admin)

    def _count():
        seen = []

        def _tap(_c, _cur, statement, _p, _ctx, _m):
            if statement.lstrip().upper().startswith('SELECT'):
                seen.append(statement)

        event.listen(db.engine, 'before_cursor_execute', _tap)
        try:
            _all_html(client)
        finally:
            event.remove(db.engine, 'before_cursor_execute', _tap)
        return len(seen)

    inst = _instance()
    _registration(inst)
    db.session.flush()
    few = _count()

    for _ in range(12):
        _registration(inst)
    db.session.flush()
    many = _count()

    assert many - few <= 4, (
        f'12 додаткових рядків дали +{many - few} SELECT ({few} -> {many})'
    )
