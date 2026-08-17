"""quiz_service: допуск, спроби, оцінювання, автовидача.

`eligibility()` -- єдине джерело правди про допуск, тож його матриця перевірена
статус за статусом: розходження між кабінетом, гейтом маршруту й адмінкою
означало б кнопку, яка веде в помилку.

Окремо перевіряється те, що коштувало б дорого: незавершена спроба НЕ витрачає
одну з трьох, набір питань не перемішується між заходами на сторінку, а
правильність відповіді не потрапляє у представлення для учасника.
"""
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_quiz import CourseQuiz, QuizQuestion
from app.models.medical_profile import MedicalProfile
from app.models.quiz_attempt import QuizAttempt
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
# Межа доби для дедлайну -- київська. Імпортуємо ту саму константу, якою її
# рахує сервіс: власна копія UTC+3 тут перевіряла б себе, а не код.
from app.utils import KYIV
from app.models.user import User
from app.services import certificate_service, quiz_service


PROVIDER = '2738'
# Власний номер заходу БПР на кожен курс: submit_attempt комітить (через
# видачу), тож сертифікати переживають відкат фікстури, і спільний номер давав
# би колізії між тестами.
_event_numbers = count(2000000)

FULL_PROFILE = {
    'participant_type': 'doctor',
    'middle_name': 'Іванович',
    'birth_date': datetime(1985, 3, 12).date(),
    'education': '2010, НМУ',
    'workplace': 'Клініка',
    'position': 'лікар',
    'specializations': ['therapy'],
}


@pytest.fixture(autouse=True)
def bpr_ready(app):
    settings = SiteSettings.get()
    settings.bpr_provider_number = PROVIDER
    settings.bpr_participant_counter = 0
    db.session.flush()
    return settings


@pytest.fixture
def no_pdf(monkeypatch):
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')


# ---- будівельники ----------------------------------------------------------

def _answers(correct=0):
    return [
        {'text': f'Варіант {i + 1}', 'is_correct': i == correct}
        for i in range(4)
    ]


def _setup(bank=12, per_attempt=10, passing=8, max_attempts=3,
           shuffle=False, active=True, cpd_points=12, event_num=None,
           paid=True, started_days_ago=1, profile=True, instance_quiz=None):
    """Курс + проведення + активний тест з банком + оплачена реєстрація."""
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'qs-{uuid4().hex[:6]}',
        is_active=True, event_type='course', cpd_points=cpd_points,
        bpr_event_number=(event_num if event_num is not None
                          else str(next(_event_numbers))),
    )
    db.session.add(course)
    db.session.flush()

    start = (datetime.now(timezone.utc) - timedelta(days=started_days_ago)
             if started_days_ago is not None else
             datetime.now(timezone.utc) + timedelta(days=7))
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ', start_date=start,
    )
    db.session.add(inst)
    db.session.flush()

    quiz = CourseQuiz(
        course_id=course.id, questions_per_attempt=per_attempt,
        passing_score=passing, max_attempts=max_attempts,
        shuffle_answers=shuffle, is_active=active,
    )
    db.session.add(quiz)
    db.session.flush()
    for i in range(bank):
        db.session.add(QuizQuestion(
            quiz_id=quiz.id, text=f'Питання {i + 1}?', answers=_answers(i % 4),
            sort_order=i,
        ))
    db.session.flush()

    user = User.create_with_password(
        f'qs-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True)
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
        specialty='Терапія', workplace='Клініка', status='confirmed',
        payment_status='paid' if paid else 'unpaid',
    )
    db.session.add(reg)
    db.session.flush()
    return reg, quiz


def _answer_all(attempt, correct_count):
    """Відповісти на всі питання; перші `correct_count` -- правильно."""
    for i, question_id in enumerate(attempt.question_ids):
        question = db.session.get(QuizQuestion, question_id)
        order = attempt.ordered_answer_indexes(question_id)
        right = order.index(question.correct_index)
        wrong = next(p for p in range(len(order)) if p != right)
        quiz_service.record_answer(
            attempt, question_id, right if i < correct_count else wrong)
    db.session.flush()


# ---- resolve_quiz ----------------------------------------------------------

def test_resolve_returns_course_quiz(app):
    reg, quiz = _setup()
    assert quiz_service.resolve_quiz(reg.instance) is quiz


def test_inactive_course_quiz_is_not_resolved(app):
    reg, _ = _setup(active=False)
    assert quiz_service.resolve_quiz(reg.instance) is None


def test_instance_override_wins(app):
    reg, course_quiz = _setup()
    override = CourseQuiz(instance_id=reg.instance_id, is_active=True)
    db.session.add(override)
    db.session.flush()
    assert quiz_service.resolve_quiz(reg.instance) is override


def test_draft_override_falls_back_to_course_quiz(app):
    """Поки адмін готує перевизначення, група складає за базовим набором."""
    reg, course_quiz = _setup()
    db.session.add(CourseQuiz(instance_id=reg.instance_id, is_active=False))
    db.session.flush()
    assert quiz_service.resolve_quiz(reg.instance) is course_quiz


# ---- матриця допуску -------------------------------------------------------

def test_available_when_everything_ready(app):
    reg, _ = _setup()
    state = quiz_service.eligibility(reg)
    assert state.status == quiz_service.AVAILABLE
    assert state.attempts_left == 3
    assert state.is_actionable is True


def test_no_quiz_takes_precedence(app):
    """Про захід без тесту не можна казати «ще не розпочався»."""
    reg, _ = _setup(active=False, started_days_ago=None, paid=False)
    assert quiz_service.eligibility(reg).status == quiz_service.NO_QUIZ


def test_cancelled_registration(app):
    reg, _ = _setup()
    reg.status = 'cancelled'
    db.session.flush()
    assert quiz_service.eligibility(reg).status == quiz_service.CANCELLED


def test_unpaid_registration(app):
    reg, _ = _setup(paid=False)
    assert quiz_service.eligibility(reg).status == quiz_service.NOT_PAID


def test_course_not_started_yet(app):
    reg, _ = _setup(started_days_ago=None)
    assert quiz_service.eligibility(reg).status == quiz_service.NOT_STARTED


@pytest.mark.parametrize('status, expected', [
    ('paid', quiz_service.AVAILABLE),
    ('unpaid', quiz_service.NOT_PAID),
    ('pending', quiz_service.NOT_PAID),
    ('refunded', quiz_service.NOT_PAID),
])
def test_gate_keys_on_payment_status_not_amount(app, status, expected):
    """Гейт дивиться на статус оплати, а не на суму.

    Це те, що робить безкоштовні заходи працездатними без окремої гілки:
    `registration_service` ставить їм `payment_status='paid'` одразу при
    створенні, хоч сума й нульова.
    """
    reg, _ = _setup()
    reg.payment_status = status
    reg.payment_amount = 0
    db.session.flush()
    assert quiz_service.eligibility(reg).status == expected


def test_bank_too_small(app):
    reg, _ = _setup(bank=5, per_attempt=10, passing=8)
    assert quiz_service.eligibility(reg).status == quiz_service.QUIZ_NOT_READY


def test_broken_question_blocks_start(app):
    reg, quiz = _setup(bank=10, per_attempt=10)
    quiz.questions[0].answers = [{'text': 'Одна', 'is_correct': True}]
    db.session.flush()
    assert quiz_service.eligibility(reg).status == quiz_service.QUIZ_NOT_READY


def test_missing_bpr_event_number_blocks_start(app):
    """Інакше людина склала б тест і отримала помилку замість сертифіката."""
    reg, _ = _setup(event_num='')
    assert quiz_service.eligibility(reg).status == quiz_service.BPR_NOT_CONFIGURED


def test_missing_provider_number_blocks_start(app, bpr_ready):
    bpr_ready.bpr_provider_number = ''
    db.session.flush()
    reg, _ = _setup()
    assert quiz_service.eligibility(reg).status == quiz_service.BPR_NOT_CONFIGURED


def test_missing_cpd_points_blocks_start(app):
    reg, _ = _setup(cpd_points=None)
    assert quiz_service.eligibility(reg).status == quiz_service.BPR_NOT_CONFIGURED


def test_incomplete_profile_blocks_start(app):
    reg, _ = _setup(profile=False)
    state = quiz_service.eligibility(reg)
    assert state.status == quiz_service.PROFILE_INCOMPLETE
    assert 'По батькові' in state.missing_fields


def test_profile_missing_only_middle_name_still_blocks(app):
    """Посилений критерій: без по батькові ПІБ на сертифікаті був би дефектним."""
    reg, _ = _setup()
    reg.user.medical_profile.middle_name = None
    db.session.flush()
    state = quiz_service.eligibility(reg)
    assert state.status == quiz_service.PROFILE_INCOMPLETE
    assert state.missing_fields == ('По батькові',)


def test_already_passed(app, no_pdf):
    reg, _ = _setup()
    reg.quiz_passed_at = datetime.now(timezone.utc)
    db.session.flush()
    assert quiz_service.eligibility(reg).status == quiz_service.PASSED


def test_in_progress_beats_other_blocks(app):
    """Почату спробу треба дати завершити, навіть якщо анкету зіпсували після."""
    reg, _ = _setup()
    quiz_service.start_attempt(reg)
    reg.user.medical_profile.workplace = None
    db.session.flush()

    state = quiz_service.eligibility(reg)
    assert state.status == quiz_service.IN_PROGRESS
    assert state.attempt is not None


def test_attempts_exhausted(app, no_pdf):
    reg, _ = _setup(max_attempts=2)
    for _ in range(2):
        attempt = quiz_service.start_attempt(reg)
        _answer_all(attempt, 0)
        quiz_service.submit_attempt(attempt)
    assert quiz_service.eligibility(reg).status == quiz_service.ATTEMPTS_EXHAUSTED


def test_admin_extra_attempt_reopens(app, no_pdf):
    reg, _ = _setup(max_attempts=1)
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 0)
    quiz_service.submit_attempt(attempt)
    assert quiz_service.eligibility(reg).status == quiz_service.ATTEMPTS_EXHAUSTED

    reg.quiz_extra_attempts = 1
    db.session.flush()
    assert quiz_service.eligibility(reg).status == quiz_service.AVAILABLE


# ---- спроби ----------------------------------------------------------------

def test_start_picks_requested_number_of_questions(app):
    reg, quiz = _setup(bank=12, per_attempt=10)
    attempt = quiz_service.start_attempt(reg)
    assert len(attempt.question_ids) == 10
    assert len(set(attempt.question_ids)) == 10, 'питання повторились'
    assert attempt.total == 10
    assert attempt.passing_score == 8


def test_start_draws_from_bank_randomly(app):
    """Банк більший за спробу -- різні спроби дають різні набори."""
    reg, _ = _setup(bank=30, per_attempt=10, max_attempts=5)
    sets = set()
    for _ in range(3):
        attempt = quiz_service.start_attempt(reg)
        sets.add(tuple(sorted(attempt.question_ids)))
        attempt.submitted_at = datetime.now(timezone.utc)
        db.session.flush()
    assert len(sets) > 1, 'вибірка не випадкова'


def test_start_skips_inactive_questions(app):
    reg, quiz = _setup(bank=11, per_attempt=10)
    quiz.questions[0].is_active = False
    db.session.flush()
    attempt = quiz_service.start_attempt(reg)
    assert quiz.questions[0].id not in attempt.question_ids


def test_start_resumes_unfinished_attempt(app):
    """Головне: закрита вкладка не з'їдає спробу."""
    reg, _ = _setup()
    first = quiz_service.start_attempt(reg)
    again = quiz_service.start_attempt(reg)
    assert again.id == first.id
    assert QuizAttempt.query.filter_by(registration_id=reg.id).count() == 1


def test_start_refuses_when_not_available(app):
    reg, _ = _setup(paid=False)
    with pytest.raises(ValueError, match='not_paid'):
        quiz_service.start_attempt(reg)


def test_attempt_numbers_increment(app, no_pdf):
    reg, _ = _setup(max_attempts=3)
    first = quiz_service.start_attempt(reg)
    _answer_all(first, 0)
    quiz_service.submit_attempt(first)
    second = quiz_service.start_attempt(reg)
    assert (first.attempt_number, second.attempt_number) == (1, 2)


def test_shuffle_produces_permutation(app):
    reg, _ = _setup(shuffle=True)
    attempt = quiz_service.start_attempt(reg)
    for question_id in attempt.question_ids:
        order = attempt.ordered_answer_indexes(question_id)
        assert sorted(order) == [0, 1, 2, 3], 'варіант втрачено або продубльовано'


def test_question_order_is_stable(app):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    snapshot = list(attempt.question_ids)
    db.session.expire_all()
    reloaded = db.session.get(QuizAttempt, attempt.id)
    assert reloaded.question_ids == snapshot


# ---- запис відповідей ------------------------------------------------------

def test_record_answer_stores_position(app):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    qid = attempt.question_ids[0]
    assert quiz_service.record_answer(attempt, qid, 2) is True
    assert attempt.chosen_position(qid) == 2


def test_record_answer_survives_reload(app):
    """JSON-колонку треба перепризначати, інакше зміна не збережеться."""
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    qid = attempt.question_ids[0]
    quiz_service.record_answer(attempt, qid, 1)
    db.session.flush()
    db.session.expire_all()
    assert db.session.get(QuizAttempt, attempt.id).chosen_position(qid) == 1


def test_record_answer_can_be_changed(app):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    qid = attempt.question_ids[0]
    quiz_service.record_answer(attempt, qid, 0)
    quiz_service.record_answer(attempt, qid, 3)
    assert attempt.chosen_position(qid) == 3


@pytest.mark.parametrize('position', [-1, 4, 99])
def test_record_answer_rejects_position_out_of_range(app, position):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    assert quiz_service.record_answer(
        attempt, attempt.question_ids[0], position) is False


def test_record_answer_rejects_foreign_question(app):
    """Питання не з цієї спроби -- підміна id у запиті."""
    reg, quiz = _setup(bank=12, per_attempt=10)
    attempt = quiz_service.start_attempt(reg)
    outsider = next(q.id for q in quiz.questions if q.id not in attempt.question_ids)
    assert quiz_service.record_answer(attempt, outsider, 0) is False


@pytest.mark.parametrize('garbage', ['abc', None, '', '1.5'])
def test_record_answer_rejects_garbage(app, garbage):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    assert quiz_service.record_answer(
        attempt, attempt.question_ids[0], garbage) is False


def test_record_answer_rejects_finished_attempt(app, no_pdf):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 0)
    quiz_service.submit_attempt(attempt)
    assert quiz_service.record_answer(attempt, attempt.question_ids[0], 0) is False


# ---- оцінювання ------------------------------------------------------------

@pytest.mark.parametrize('correct, expected_pass', [
    (10, True), (8, True), (7, False), (0, False),
])
def test_passing_boundary(app, no_pdf, correct, expected_pass):
    """Межа 8 з 10 -- рівно те правило, яке задав замовник."""
    reg, _ = _setup(passing=8)
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, correct)
    quiz_service.submit_attempt(attempt)
    assert attempt.score == correct
    assert attempt.passed is expected_pass


def test_unanswered_counts_as_wrong(app, no_pdf):
    reg, _ = _setup(passing=8)
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 10)
    # Прибираємо дві відповіді -- ніби людина їх пропустила.
    answers = dict(attempt.submitted_answers)
    for qid in attempt.question_ids[:2]:
        answers.pop(str(qid))
    attempt.submitted_answers = answers
    db.session.flush()

    quiz_service.submit_attempt(attempt)
    assert attempt.score == 8


def test_grading_follows_shuffled_order(app, no_pdf):
    """Перевірка мапінгу: позиція -> реальний індекс варіанта."""
    reg, _ = _setup(shuffle=True, passing=1, per_attempt=1, bank=4)
    attempt = quiz_service.start_attempt(reg)
    qid = attempt.question_ids[0]
    question = db.session.get(QuizQuestion, qid)
    order = attempt.ordered_answer_indexes(qid)

    quiz_service.record_answer(attempt, qid, order.index(question.correct_index))
    assert quiz_service.grade_attempt(attempt) == 1

    wrong = next(p for p, orig in enumerate(order) if orig != question.correct_index)
    quiz_service.record_answer(attempt, qid, wrong)
    assert quiz_service.grade_attempt(attempt) == 0


def test_submit_is_idempotent(app, no_pdf):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 10)
    quiz_service.submit_attempt(attempt)
    first_time, first_score = attempt.submitted_at, attempt.score

    quiz_service.submit_attempt(attempt)
    assert (attempt.submitted_at, attempt.score) == (first_time, first_score)
    assert Certificate.query.filter_by(registration_id=reg.id).count() == 1


def test_failed_attempt_leaves_registration_untouched(app, no_pdf):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 3)
    quiz_service.submit_attempt(attempt)

    assert reg.quiz_passed_at is None
    assert reg.attended is not True
    assert reg.certificate is None


# ---- автовидача ------------------------------------------------------------

def test_passing_issues_certificate(app, no_pdf):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 10)
    quiz_service.submit_attempt(attempt)

    assert reg.quiz_passed_at is not None
    assert reg.certificate is not None
    assert reg.certificate.cpd_points == 12


def test_passing_marks_attendance_and_points(app, no_pdf):
    """Успішний тест і є підтвердженням участі -- бали не чекають адміна."""
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 9)
    quiz_service.submit_attempt(attempt)

    assert reg.attended is True
    assert reg.cpd_points_awarded == 12


def test_admin_awarded_points_are_not_overwritten(app, no_pdf):
    reg, _ = _setup()
    reg.cpd_points_awarded = 6
    db.session.flush()
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 10)
    quiz_service.submit_attempt(attempt)
    assert reg.cpd_points_awarded == 6


@pytest.mark.parametrize('error', [
    ValueError('Не задано реєстраційний номер заходу БПР'),
    RuntimeError('WeasyPrint недоступний'),
])
def test_issue_failure_keeps_passed_state(app, monkeypatch, error):
    """Провал видачі не має відкочувати зафіксований результат тесту.

    Саме тому результат комітиться ДО видачі: спільний коміт із видачею забрав
    би з собою і складений тест, і спробу.
    """
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 10)

    def _boom(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(certificate_service, 'issue_certificate', _boom)
    quiz_service.submit_attempt(attempt)

    assert attempt.passed is True
    assert reg.quiz_passed_at is not None
    assert reg.certificate is None


def test_issue_failure_keeps_attendance_and_points(app, monkeypatch):
    """Присутність і бали комітяться окремо, до видачі."""
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 10)

    monkeypatch.setattr(
        certificate_service, 'issue_certificate',
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError('збій')))
    quiz_service.submit_attempt(attempt)

    db.session.expire_all()
    fresh = db.session.get(EventRegistration, reg.id)
    assert fresh.attended is True
    assert fresh.cpd_points_awarded == 12
    assert fresh.quiz_passed_at is not None


# ---- банк питань: форма <-> БД ---------------------------------------------

def _form(count_questions=2, correct='1'):
    data = {}
    for i in range(count_questions):
        data[f'question_{i}_id'] = ''
        data[f'question_{i}_text'] = f'Питання {i + 1}?'
        data[f'question_{i}_correct'] = correct
        for j in range(4):
            data[f'question_{i}_answer_{j}_text'] = f'Відповідь {j + 1}'
    return data


def test_extract_reads_indexed_fields(app):
    parsed = quiz_service.extract_questions_from_form(_form(2))
    assert len(parsed) == 2
    assert parsed[0]['text'] == 'Питання 1?'
    assert [a['is_correct'] for a in parsed[0]['answers']] == \
        [False, True, False, False]


def test_extract_stops_at_first_gap(app):
    data = _form(2)
    del data['question_1_text']
    assert len(quiz_service.extract_questions_from_form(data)) == 1


def test_extract_skips_empty_question(app):
    data = _form(2)
    data['question_0_text'] = '   '
    parsed = quiz_service.extract_questions_from_form(data)
    assert [q['text'] for q in parsed] == ['Питання 2?']


def test_extract_tolerates_broken_id(app):
    data = _form(1)
    data['question_0_id'] = 'не-число'
    assert quiz_service.extract_questions_from_form(data)[0]['id'] is None


def test_extract_without_correct_marks_none(app):
    data = _form(1, correct='')
    answers = quiz_service.extract_questions_from_form(data)[0]['answers']
    assert not any(a['is_correct'] for a in answers)


def test_save_creates_updates_and_deletes(app):
    reg, quiz = _setup(bank=0, per_attempt=1, passing=1)
    quiz_service.save_questions_for_quiz(
        quiz, quiz_service.extract_questions_from_form(_form(3)))
    db.session.flush()
    assert len(quiz.questions) == 3

    kept = quiz.questions[0]
    data = _form(1)
    data['question_0_id'] = str(kept.id)
    data['question_0_text'] = 'Оновлене питання?'
    quiz_service.save_questions_for_quiz(
        quiz, quiz_service.extract_questions_from_form(data))
    db.session.flush()

    assert len(quiz.questions) == 1
    assert quiz.questions[0].id == kept.id
    assert quiz.questions[0].text == 'Оновлене питання?'


def test_save_assigns_sort_order(app):
    reg, quiz = _setup(bank=0, per_attempt=1, passing=1)
    quiz_service.save_questions_for_quiz(
        quiz, quiz_service.extract_questions_from_form(_form(3)))
    db.session.flush()
    assert [q.sort_order for q in quiz.questions] == [0, 1, 2]


# ---- діагностика для адмінки ------------------------------------------------

def test_validation_reports_small_bank(app):
    reg, quiz = _setup(bank=4, per_attempt=10)
    errors = quiz_service.validation_errors(quiz)
    assert any('4 активних питань' in e for e in errors)


def test_validation_reports_broken_question(app):
    reg, quiz = _setup(bank=10, per_attempt=10)
    quiz.questions[0].answers = [{'text': 'Одна', 'is_correct': True}]
    db.session.flush()
    errors = quiz_service.validation_errors(quiz)
    assert any('рівно 4' in e for e in errors)


def test_validation_reports_missing_correct(app):
    reg, quiz = _setup(bank=10, per_attempt=10)
    quiz.questions[0].answers = [
        dict(a, is_correct=False) for a in _answers()]
    db.session.flush()
    errors = quiz_service.validation_errors(quiz)
    assert any('одну правильну' in e for e in errors)


def test_validation_silent_when_ready(app):
    reg, quiz = _setup(bank=10, per_attempt=10)
    assert quiz_service.validation_errors(quiz) == []


# ---- представлення для учасника --------------------------------------------

def test_view_model_never_exposes_correctness(app):
    """Єдине місце, що будує питання для учасника -- витік тут неможливий."""
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    view = quiz_service.attempt_view_model(attempt, 0)

    serialized = repr(view)
    assert 'is_correct' not in serialized
    assert set(view['answers'][0]) == {'position', 'text'}
    assert len(view['answers']) == 4


def test_view_model_numbers_questions(app):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    view = quiz_service.attempt_view_model(attempt, 3)
    assert (view['number'], view['total']) == (4, 10)


def test_view_model_returns_chosen_answer(app):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    quiz_service.record_answer(attempt, attempt.question_ids[0], 2)
    assert quiz_service.attempt_view_model(attempt, 0)['chosen'] == 2


@pytest.mark.parametrize('position', [-1, 10, 99])
def test_view_model_rejects_position_out_of_range(app, position):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    assert quiz_service.attempt_view_model(attempt, position) is None


# ---- питання, видалене під час спроби ---------------------------------------

def test_deleted_question_is_not_counted_against_participant(app, no_pdf):
    """Адмін видалив питання, поки людина проходила тест.

    Перевірити відповідь уже неможливо, і карати за це учасника нема за що: він
    не актор цієї зміни, а спроб у нього лише три. Раніше таке питання тихо
    ставало помилкою.
    """
    reg, quiz = _setup(bank=12, per_attempt=10, passing=10)
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 10)

    victim_id = attempt.question_ids[0]
    db.session.delete(db.session.get(QuizQuestion, victim_id))
    db.session.flush()

    assert quiz_service.grade_attempt(attempt) == 10
    assert victim_id not in [
        qid for _n, qid, ok in quiz_service.question_results(attempt) if not ok
    ]


def test_deleted_question_leaves_other_answers_intact(app, no_pdf):
    """Решта питань оцінюється як звичайно."""
    reg, quiz = _setup(bank=12, per_attempt=10, passing=8)
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 8)      # два останні -- неправильні

    # Видаляємо питання, на яке відповіли ПРАВИЛЬНО: оцінка не має змінитись.
    db.session.delete(db.session.get(QuizQuestion, attempt.question_ids[0]))
    db.session.flush()

    assert quiz_service.grade_attempt(attempt) == 8
    assert quiz_service.wrong_numbers(attempt) == [9, 10]


def test_deleted_question_forgives_a_wrong_answer(app, no_pdf):
    """Свідома ціна політики: видалене питання прощається, навіть якщо на нього
    відповіли неправильно.

    Альтернатива -- карати за питання, якого вже немає, а перевірити відповідь
    неможливо. Актор тут адмін, а не учасник, тож помилятися краще на його
    користь. Випадок логується як WARNING.
    """
    reg, quiz = _setup(bank=12, per_attempt=10, passing=8)
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 8)      # питання 9 і 10 -- неправильні

    db.session.delete(db.session.get(QuizQuestion, attempt.question_ids[8]))
    db.session.flush()

    assert quiz_service.grade_attempt(attempt) == 9
    assert quiz_service.wrong_numbers(attempt) == [10]


# ---- єдине джерело оцінювання ----------------------------------------------

def test_wrong_numbers_agrees_with_score(app):
    """Оцінка і перелік незарахованих ідуть з однієї функції."""
    reg, _ = _setup(bank=12, per_attempt=10, passing=8)
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 6)

    score = quiz_service.grade_attempt(attempt)
    wrong = quiz_service.wrong_numbers(attempt)
    assert score == 6
    assert len(wrong) == attempt.total - score


def test_unanswered_appears_in_wrong_numbers(app):
    reg, _ = _setup(bank=12, per_attempt=10, passing=8)
    attempt = quiz_service.start_attempt(reg)
    # Відповідаємо лише на перше питання.
    question = db.session.get(QuizQuestion, attempt.question_ids[0])
    order = attempt.ordered_answer_indexes(question.id)
    quiz_service.record_answer(
        attempt, question.id, order.index(question.correct_index))

    assert quiz_service.wrong_numbers(attempt) == list(range(2, 11))


# ---- подвійний старт --------------------------------------------------------

def test_concurrent_start_reuses_attempt(app, monkeypatch):
    """Подвійне натискання «Почати тест» не має давати 500.

    Імітуємо гонку: перший запит уже вставив спробу з тим самим
    attempt_number, тож flush другого падає на unique-констрейнті.
    """
    reg, _ = _setup()
    first = quiz_service.start_attempt(reg)
    db.session.commit()

    # Друга спроба «не бачить» першої -- підміняємо пошук незавершеної.
    calls = {'n': 0}
    real = quiz_service._unfinished_attempt

    def _blind_once(registration, context=None):
        calls['n'] += 1
        return None if calls['n'] == 1 else real(registration, context)

    monkeypatch.setattr(quiz_service, '_unfinished_attempt', _blind_once)

    again = quiz_service.start_attempt(reg)
    assert again.id == first.id
    assert QuizAttempt.query.filter_by(registration_id=reg.id).count() == 1


# ---- лист із сертифікатом при автовидачі ------------------------------------

def test_passing_sends_certificate_email(app, no_pdf, monkeypatch):
    """Автовидача мусить надсилати лист, як і ручна.

    Без цього кроку сертифікат з'являвся лише в кабінеті, а сторінка привітання
    обіцяла «копію надіслано на вашу пошту» -- тобто казала неправду.
    """
    from app.services.email_service import EmailService

    sent = []
    monkeypatch.setattr(EmailService, 'send_certificate',
                        staticmethod(lambda cert: sent.append(cert.number)))

    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 10)
    quiz_service.submit_attempt(attempt)

    assert sent == [reg.certificate.number]


def test_email_failure_does_not_lose_certificate(app, no_pdf, monkeypatch):
    """Лист -- best-effort: сертифікат уже закомічений."""
    from app.services.email_service import EmailService

    def _boom(_cert):
        raise RuntimeError('SMTP недоступний')

    monkeypatch.setattr(EmailService, 'send_certificate', staticmethod(_boom))

    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 10)
    quiz_service.submit_attempt(attempt)

    db.session.expire_all()
    fresh = db.session.get(EventRegistration, reg.id)
    assert fresh.certificate is not None
    assert fresh.quiz_passed_at is not None


def test_certificate_email_sent_reads_the_log(app, no_pdf):
    """Стан відправки відновлюється з журналу, а не з пам'яті запиту."""
    from app.models.email_log import EmailLog

    reg, _ = _setup()
    assert quiz_service.certificate_email_sent(reg) is False

    db.session.add(EmailLog(
        to_email=reg.user.email, subject='Ваш сертифікат',
        template_name='certificate_issued', status='sent',
        trigger='certificate', registration_id=reg.id))
    db.session.flush()
    assert quiz_service.certificate_email_sent(reg) is True


def test_failed_email_log_does_not_count_as_sent(app, no_pdf):
    from app.models.email_log import EmailLog

    reg, _ = _setup()
    db.session.add(EmailLog(
        to_email=reg.user.email, subject='Ваш сертифікат',
        template_name='certificate_issued', status='failed',
        trigger='certificate', registration_id=reg.id))
    db.session.flush()
    assert quiz_service.certificate_email_sent(reg) is False


# ---- статус реєстрації ------------------------------------------------------

def test_passing_marks_registration_completed(app, no_pdf):
    """Ручна відмітка присутності ставить status='completed' -- автовидача теж.

    Інакше два шляхи «участь відбулась» дають різні стани: кабінет показував би
    «Підтверджено» людині з сертифікатом, а адмінський фільтр «без сертифіката»
    (status='completed') таких реєстрацій не бачив би.
    """
    reg, _ = _setup()
    assert reg.status == 'confirmed'

    attempt = quiz_service.start_attempt(reg)
    _answer_all(attempt, 10)
    quiz_service.submit_attempt(attempt)

    assert reg.status == 'completed'
    assert reg.attended is True


# ---- батч-контекст ----------------------------------------------------------

def test_batch_context_matches_single_calls(app):
    """Батч не має бути другою реалізацією правил: результати мусять збігатися."""
    regs = [_setup()[0] for _ in range(3)]
    regs[0].payment_status = 'unpaid'
    regs[1].user.medical_profile.workplace = None
    db.session.flush()

    batched = quiz_service.eligibility_map(regs)
    for reg in regs:
        single = quiz_service.eligibility(reg)
        assert batched[reg.id].status == single.status
        assert batched[reg.id].attempts_left == single.attempts_left
        assert batched[reg.id].missing_fields == single.missing_fields


def test_batch_context_sees_in_progress_attempt(app):
    reg, _ = _setup()
    quiz_service.start_attempt(reg)
    db.session.flush()

    state = quiz_service.eligibility_map([reg])[reg.id]
    assert state.status == quiz_service.IN_PROGRESS
    assert state.attempt is not None


def test_batch_context_handles_instance_override(app):
    reg, _ = _setup()
    override = CourseQuiz(instance_id=reg.instance_id, is_active=True)
    db.session.add(override)
    db.session.flush()

    assert quiz_service.eligibility_map([reg])[reg.id].quiz is override


def test_eligibility_map_empty_input(app):
    assert quiz_service.eligibility_map([]) == {}


# ---- батч представлень питань -----------------------------------------------

def test_attempt_view_models_returns_all_questions(app):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    views = quiz_service.attempt_view_models(attempt)

    assert [v['number'] for v in views] == list(range(1, 11))
    assert all(set(v['answers'][0]) == {'position', 'text'} for v in views)


def test_attempt_view_models_skips_deleted_question(app):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    db.session.delete(db.session.get(QuizQuestion, attempt.question_ids[0]))
    db.session.flush()

    views = quiz_service.attempt_view_models(attempt)
    assert len(views) == 9


def test_attempt_view_models_never_leak_correctness(app):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    assert 'is_correct' not in repr(quiz_service.attempt_view_models(attempt))


# --- дедлайн складання --------------------------------------------------------
#
# Роздатка учасникам обіцяла «до 23:59 у день завершення заходу», а тест
# відкривався з початком заходу і не закривався ніколи. NULL зберігає стару
# поведінку, 0 означає рівно те, що в роздатці.

class TestDeadline:

    def test_no_deadline_by_default(self, app):
        reg, quiz = _setup()
        assert quiz.deadline_days_after_end is None
        assert quiz_service.deadline_for(quiz, reg.instance) is None
        assert quiz_service.eligibility(reg).status == quiz_service.AVAILABLE

    def test_zero_days_means_end_of_the_last_day(self, app):
        """0 -- до 23:59 київського дня, коли захід завершився."""
        reg, quiz = _setup()
        reg.instance.end_date = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
        quiz.deadline_days_after_end = 0
        db.session.flush()

        deadline = quiz_service.deadline_for(quiz, reg.instance)
        local = deadline.astimezone(KYIV)
        assert (local.year, local.month, local.day) == (2026, 8, 20)
        assert (local.hour, local.minute) == (23, 59)

    def test_counted_from_end_not_from_start(self, app):
        """На триденному заході відлік від початку закрив би тест посеред нього."""
        reg, quiz = _setup()
        reg.instance.start_date = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)
        reg.instance.end_date = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
        quiz.deadline_days_after_end = 0
        db.session.flush()

        local = quiz_service.deadline_for(quiz, reg.instance).astimezone(KYIV)
        assert local.day == 20

    def test_falls_back_to_start_when_end_is_empty(self, app):
        reg, quiz = _setup()
        reg.instance.start_date = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)
        reg.instance.end_date = None
        quiz.deadline_days_after_end = 0
        db.session.flush()

        local = quiz_service.deadline_for(quiz, reg.instance).astimezone(KYIV)
        assert local.day == 18

    def test_extra_days_shift_the_window(self, app):
        reg, quiz = _setup()
        reg.instance.end_date = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
        quiz.deadline_days_after_end = 3
        db.session.flush()

        local = quiz_service.deadline_for(quiz, reg.instance).astimezone(KYIV)
        assert local.day == 23

    def test_expired_window_blocks_the_start(self, app):
        reg, quiz = _setup()
        reg.instance.end_date = datetime.now(timezone.utc) - timedelta(days=5)
        quiz.deadline_days_after_end = 0
        db.session.flush()

        state = quiz_service.eligibility(reg)
        assert state.status == quiz_service.DEADLINE_PASSED
        assert state.deadline is not None

    def test_open_window_still_allows_the_start(self, app):
        reg, quiz = _setup()
        reg.instance.end_date = datetime.now(timezone.utc) - timedelta(hours=1)
        quiz.deadline_days_after_end = 1
        db.session.flush()

        state = quiz_service.eligibility(reg)
        assert state.status == quiz_service.AVAILABLE
        assert state.deadline is not None

    def test_started_attempt_can_be_finished_after_the_deadline(self, app):
        """Обривати тест на середині за годинником -- це з'їсти спробу дарма."""
        reg, quiz = _setup()
        reg.instance.end_date = datetime.now(timezone.utc) - timedelta(hours=2)
        quiz.deadline_days_after_end = 0
        db.session.flush()

        # Спроба почата, доки вікно ще було відкрите.
        quiz.deadline_days_after_end = None
        db.session.flush()
        attempt = quiz_service.start_attempt(reg)
        quiz.deadline_days_after_end = 0
        reg.instance.end_date = datetime.now(timezone.utc) - timedelta(days=5)
        db.session.flush()

        state = quiz_service.eligibility(reg)
        assert state.status == quiz_service.IN_PROGRESS
        assert state.attempt.id == attempt.id

    def test_passed_wins_over_deadline(self, app):
        """Складений тест не має ставати «прострочений» назавтра."""
        reg, quiz = _setup()
        reg.quiz_passed_at = datetime.now(timezone.utc)
        reg.instance.end_date = datetime.now(timezone.utc) - timedelta(days=30)
        quiz.deadline_days_after_end = 0
        db.session.flush()

        assert quiz_service.eligibility(reg).status == quiz_service.PASSED

    def test_label_is_in_kyiv_time(self, app):
        deadline = datetime(2026, 8, 20, 20, 59, 59, tzinfo=timezone.utc)
        assert quiz_service.deadline_label(deadline) == '20.08.2026, 23:59'

    def test_label_of_none_is_empty(self, app):
        assert quiz_service.deadline_label(None) == ''

    def test_deadline_survives_batch_context(self, app):
        """Батч-шлях мусить давати той самий статус, що й поштучний."""
        reg, quiz = _setup()
        reg.instance.end_date = datetime.now(timezone.utc) - timedelta(days=5)
        quiz.deadline_days_after_end = 0
        db.session.flush()

        states = quiz_service.eligibility_map([reg])
        assert states[reg.id].status == quiz_service.DEADLINE_PASSED
