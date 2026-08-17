"""Публічний потік тестування: доступ, збереження відповідей, завершення.

Тут закріплено три речі, які дорого коштували б у проді:

* правильні відповіді НЕ потрапляють у HTML -- інакше тест безглуздий;
* чужу спробу неможливо ні побачити, ні продовжити, ні завершити;
* закрита вкладка не з'їдає спробу -- незавершена продовжується з того ж місця,
  а завершити можна лише коли відповіді є на всі питання.
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
from app.models.quiz_attempt import QuizAttempt
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import certificate_service, quiz_service

_event_numbers = count(4000000)

FULL_PROFILE = {
    'participant_type': 'doctor', 'middle_name': 'Іванович',
    'birth_date': datetime(1985, 3, 12).date(), 'education': '2010, НМУ',
    'workplace': 'Клініка', 'position': 'лікар', 'specializations': ['therapy'],
}

# Текст, за яким шукаємо витік: у банку лише один правильний варіант, і його
# рядок унікальний, тож будь-яка згадка в HTML була б витоком.
CORRECT_TEXT = 'ПРАВИЛЬНА-ВІДПОВІДЬ'
WRONG_TEXT = 'хибний варіант'


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


def _user(profile=True):
    user = User.create_with_password(
        f'q-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Іван', last_name='Тестовий', email_confirmed=True)
    db.session.flush()
    if profile:
        prof = user.medical_profile or MedicalProfile(user_id=user.id)
        for field, value in FULL_PROFILE.items():
            setattr(prof, field, value)
        user.medical_profile = prof
        db.session.add(prof)
    db.session.flush()
    return user


def _setup(bank=10, per_attempt=10, passing=8, max_attempts=3, active=True,
           paid=True, started=True, profile=True, event_num=None):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'qr-{uuid4().hex[:6]}',
        is_active=True, event_type='course', cpd_points=12,
        bpr_event_number=(event_num if event_num is not None
                          else str(next(_event_numbers))),
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        start_date=(datetime.now(timezone.utc) - timedelta(days=1) if started
                    else datetime.now(timezone.utc) + timedelta(days=7)),
    )
    db.session.add(inst)
    db.session.flush()

    quiz = CourseQuiz(
        course_id=course.id, questions_per_attempt=per_attempt,
        passing_score=passing, max_attempts=max_attempts,
        shuffle_answers=False, is_active=active,
    )
    db.session.add(quiz)
    db.session.flush()
    for i in range(bank):
        db.session.add(QuizQuestion(
            quiz_id=quiz.id, text=f'Питання {i + 1}?', sort_order=i,
            answers=[
                {'text': WRONG_TEXT + ' 1', 'is_correct': False},
                {'text': CORRECT_TEXT, 'is_correct': True},
                {'text': WRONG_TEXT + ' 3', 'is_correct': False},
                {'text': WRONG_TEXT + ' 4', 'is_correct': False},
            ],
        ))
    db.session.flush()

    user = _user(profile=profile)
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='confirmed',
        payment_status='paid' if paid else 'unpaid')
    db.session.add(reg)
    db.session.flush()
    return reg, quiz


def _answer_all(client, attempt, correct_count):
    """Пройти всі питання через HTTP, як це робить браузер."""
    for position, question_id in enumerate(attempt.question_ids):
        question = db.session.get(QuizQuestion, question_id)
        order = attempt.ordered_answer_indexes(question_id)
        right = order.index(question.correct_index)
        wrong = next(p for p in range(len(order)) if p != right)
        client.post(f'/quiz/attempt/{attempt.id}/answer', data={
            'position': str(position),
            'question_id': str(question_id),
            'choice': str(right if position < correct_count else wrong),
            'direction': 'next',
        })


# ---- доступ -----------------------------------------------------------------

def test_anonymous_is_redirected_to_login(client, app):
    reg, _ = _setup()
    db.session.commit()
    resp = client.get(f'/quiz/{reg.id}')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_foreign_registration_is_404(client, app):
    reg, _ = _setup()
    intruder = _user()
    _login(client, intruder)
    assert client.get(f'/quiz/{reg.id}').status_code == 404


def test_missing_registration_is_404(client, app):
    _login(client, _user())
    assert client.get('/quiz/999999').status_code == 404


def test_foreign_attempt_cannot_be_viewed(client, app):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    db.session.commit()

    _login(client, _user())
    assert client.get(f'/quiz/attempt/{attempt.id}').status_code == 404


def test_foreign_attempt_cannot_be_submitted(client, app):
    reg, _ = _setup()
    attempt = quiz_service.start_attempt(reg)
    db.session.commit()

    _login(client, _user())
    assert client.post(f'/quiz/attempt/{attempt.id}/submit').status_code == 404
    db.session.expire_all()
    assert db.session.get(QuizAttempt, attempt.id).is_finished is False


def test_pages_are_noindex(client, app):
    reg, _ = _setup()
    _login(client, reg.user)
    resp = client.get(f'/quiz/{reg.id}')
    assert resp.headers.get('X-Robots-Tag') == 'noindex, nofollow'


# ---- сторінка умов ----------------------------------------------------------

def test_start_shows_terms(client, app):
    reg, _ = _setup()
    _login(client, reg.user)
    html = client.get(f'/quiz/{reg.id}').get_data(as_text=True)
    assert 'Почати тест' in html
    assert 'Спроб залишилось' in html


def test_start_blocks_incomplete_profile_and_names_gaps(client, app):
    reg, _ = _setup(profile=False)
    _login(client, reg.user)
    html = client.get(f'/quiz/{reg.id}').get_data(as_text=True)
    assert 'Заповнити анкету' in html
    assert 'По батькові' in html
    assert 'Почати тест' not in html


def test_start_blocks_unpaid(client, app):
    reg, _ = _setup(paid=False)
    _login(client, reg.user)
    html = client.get(f'/quiz/{reg.id}').get_data(as_text=True)
    assert 'після оплати' in html


def test_start_blocks_before_event(client, app):
    reg, _ = _setup(started=False)
    _login(client, reg.user)
    html = client.get(f'/quiz/{reg.id}').get_data(as_text=True)
    assert 'після початку заходу' in html


def test_begin_refuses_when_blocked(client, app):
    reg, _ = _setup(paid=False)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    assert QuizAttempt.query.filter_by(registration_id=reg.id).count() == 0


# ---- проходження ------------------------------------------------------------

def test_question_page_never_reveals_correct_answer(client, app):
    """Найважливіший тест усього потоку."""
    reg, _ = _setup()
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    html = client.get(f'/quiz/attempt/{attempt.id}').get_data(as_text=True)
    assert 'is_correct' not in html
    assert 'correct_index' not in html
    # Сам текст правильного варіанта показується (він один з чотирьох), але
    # нічим не позначений: перевіряємо, що поруч немає маркерів.
    assert html.count(CORRECT_TEXT) == 1
    assert 'data-correct' not in html


def test_answer_is_saved_and_shown_checked(client, app):
    reg, _ = _setup()
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    qid = attempt.question_ids[0]

    client.post(f'/quiz/attempt/{attempt.id}/answer', data={
        'position': '0', 'question_id': str(qid), 'choice': '2',
        'direction': 'next',
    })
    db.session.expire_all()
    assert db.session.get(QuizAttempt, attempt.id).chosen_position(qid) == 2

    html = client.get(f'/quiz/attempt/{attempt.id}?position=0').get_data(as_text=True)
    assert 'value="2"' in html and 'checked' in html


def test_next_and_back_navigation(client, app):
    reg, _ = _setup()
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    resp = client.post(f'/quiz/attempt/{attempt.id}/answer', data={
        'position': '0', 'question_id': str(attempt.question_ids[0]),
        'choice': '1', 'direction': 'next',
    })
    assert 'position=1' in resp.headers['Location']

    resp = client.post(f'/quiz/attempt/{attempt.id}/answer', data={
        'position': '1', 'question_id': str(attempt.question_ids[1]),
        'choice': '1', 'direction': 'back',
    })
    assert 'position=0' in resp.headers['Location']


def test_last_question_leads_to_review(client, app):
    reg, _ = _setup(bank=2, per_attempt=2, passing=1)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    resp = client.post(f'/quiz/attempt/{attempt.id}/answer', data={
        'position': '1', 'question_id': str(attempt.question_ids[1]),
        'choice': '1', 'direction': 'next',
    })
    assert '/review' in resp.headers['Location']


def test_empty_choice_is_not_an_error(client, app):
    """«Далі» без вибору -- людина хоче повернутися до питання пізніше."""
    reg, _ = _setup()
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    resp = client.post(f'/quiz/attempt/{attempt.id}/answer', data={
        'position': '0', 'question_id': str(attempt.question_ids[0]),
        'choice': '', 'direction': 'next',
    })
    assert resp.status_code == 302
    db.session.expire_all()
    assert db.session.get(QuizAttempt, attempt.id).answered_count == 0


def test_out_of_range_position_redirects(client, app):
    reg, _ = _setup()
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    resp = client.get(f'/quiz/attempt/{attempt.id}?position=999')
    assert resp.status_code == 302


def test_resume_continues_same_attempt(client, app):
    """Закрита вкладка не має коштувати спроби."""
    reg, _ = _setup()
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    first = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    html = client.get(f'/quiz/{reg.id}').get_data(as_text=True)
    assert 'Продовжити тест' in html

    client.post(f'/quiz/{reg.id}/start')
    assert QuizAttempt.query.filter_by(registration_id=reg.id).count() == 1
    assert QuizAttempt.query.filter_by(registration_id=reg.id).one().id == first.id


def test_resume_opens_first_unanswered(client, app):
    reg, _ = _setup()
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    for position in range(3):
        client.post(f'/quiz/attempt/{attempt.id}/answer', data={
            'position': str(position),
            'question_id': str(attempt.question_ids[position]),
            'choice': '1', 'direction': 'next',
        })

    html = client.get(f'/quiz/attempt/{attempt.id}').get_data(as_text=True)
    assert 'Питання 4 з 10' in html


# ---- звірка й завершення ----------------------------------------------------

def test_review_lists_unanswered(client, app):
    reg, _ = _setup(bank=2, per_attempt=2, passing=1)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    html = client.get(f'/quiz/attempt/{attempt.id}/review').get_data(as_text=True)
    assert 'Немає відповіді на питання' in html
    assert 'Завершити тест' not in html


def test_submit_refuses_with_unanswered(client, app):
    """Випадковий клік «Завершити» не має спалювати спробу."""
    reg, _ = _setup()
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    resp = client.post(f'/quiz/attempt/{attempt.id}/submit', follow_redirects=True)
    assert 'Спершу відповідьте на всі питання' in resp.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(QuizAttempt, attempt.id).is_finished is False


def test_review_never_reveals_correctness(client, app):
    reg, _ = _setup(bank=2, per_attempt=2, passing=1)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 2)

    html = client.get(f'/quiz/attempt/{attempt.id}/review').get_data(as_text=True)
    assert 'is_correct' not in html


def test_full_pass_flow_issues_certificate(client, app, no_pdf):
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)

    resp = client.post(f'/quiz/attempt/{attempt.id}/submit', follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert 'Тест складено' in html
    assert '10 <span class="quiz-result__of">/ 10</span>' in html

    db.session.expire_all()
    fresh = db.session.get(EventRegistration, reg.id)
    assert fresh.quiz_passed_at is not None
    assert fresh.certificate is not None


def test_failed_flow_offers_retry_without_answers(client, app, no_pdf):
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 3)

    resp = client.post(f'/quiz/attempt/{attempt.id}/submit', follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert 'Тест не складено' in html
    assert 'Спробувати ще раз' in html
    assert 'Не зараховані питання' in html
    # Номери -- так, правильні відповіді -- ні.
    assert CORRECT_TEXT not in html


def test_second_submit_does_not_change_result(client, app, no_pdf):
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)
    client.post(f'/quiz/attempt/{attempt.id}/submit')

    db.session.expire_all()
    finished = db.session.get(QuizAttempt, attempt.id)
    submitted_at, score = finished.submitted_at, finished.score

    client.post(f'/quiz/attempt/{attempt.id}/submit')
    db.session.expire_all()
    again = db.session.get(QuizAttempt, attempt.id)
    assert (again.submitted_at, again.score) == (submitted_at, score)


def test_answer_after_finish_is_ignored(client, app, no_pdf):
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)
    client.post(f'/quiz/attempt/{attempt.id}/submit')

    resp = client.post(f'/quiz/attempt/{attempt.id}/answer', data={
        'position': '0', 'question_id': str(attempt.question_ids[0]),
        'choice': '0', 'direction': 'next',
    })
    assert '/result' in resp.headers['Location']
    db.session.expire_all()
    assert db.session.get(QuizAttempt, attempt.id).score == 10


def test_finished_attempt_question_page_redirects_to_result(client, app, no_pdf):
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)
    client.post(f'/quiz/attempt/{attempt.id}/submit')

    resp = client.get(f'/quiz/attempt/{attempt.id}')
    assert '/result' in resp.headers['Location']


# ---- сторінка привітання ----------------------------------------------------

def test_done_shows_certificate_link(client, app, no_pdf):
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)
    client.post(f'/quiz/attempt/{attempt.id}/submit')

    html = client.get(f'/quiz/{reg.id}/done').get_data(as_text=True)
    assert 'Вітаємо!' in html
    db.session.expire_all()
    cert = db.session.get(EventRegistration, reg.id).certificate
    assert f'/auth/account/certificates/{cert.id}/download' in html
    assert cert.number in html


def test_done_redirects_when_not_passed(client, app):
    reg, _ = _setup()
    _login(client, reg.user)
    resp = client.get(f'/quiz/{reg.id}/done')
    assert resp.status_code == 302
    assert f'/quiz/{reg.id}' in resp.headers['Location']


def test_start_redirects_to_done_when_passed(client, app, no_pdf):
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)
    client.post(f'/quiz/attempt/{attempt.id}/submit')

    resp = client.get(f'/quiz/{reg.id}')
    assert '/done' in resp.headers['Location']


def test_done_without_certificate_reassures(client, app, monkeypatch):
    """Видача впала -- людина мусить бачити, що результат збережено."""
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    monkeypatch.setattr(
        certificate_service, 'issue_certificate',
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError('збій')))
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)
    client.post(f'/quiz/attempt/{attempt.id}/submit')

    html = client.get(f'/quiz/{reg.id}/done').get_data(as_text=True)
    assert 'Сертифікат готується' in html
    assert 'повторно складати не потрібно' in html


# ---- вхід із кабінету -------------------------------------------------------

def test_account_offers_quiz_when_available(client, app):
    """Кабінет -- єдиний вхід у тест: без кнопки до нього не дійти."""
    reg, _ = _setup()
    _login(client, reg.user)
    html = client.get('/auth/account').get_data(as_text=True)
    assert 'Пройти тестування' in html
    assert f'/quiz/{reg.id}' in html


def test_account_offers_continue_for_started_attempt(client, app):
    reg, _ = _setup()
    quiz_service.start_attempt(reg)
    db.session.commit()
    _login(client, reg.user)
    html = client.get('/auth/account').get_data(as_text=True)
    assert 'Продовжити тестування' in html


def test_account_points_to_form_when_profile_incomplete(client, app):
    reg, _ = _setup(profile=False)
    _login(client, reg.user)
    html = client.get('/auth/account').get_data(as_text=True)
    assert 'Заповніть анкету, щоб пройти тестування' in html


def test_account_shows_passed_state(client, app, no_pdf):
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)
    client.post(f'/quiz/attempt/{attempt.id}/submit')

    html = client.get('/auth/account').get_data(as_text=True)
    assert 'Тестування складено' in html


def test_account_silent_when_no_quiz(client, app):
    """Заходи без тесту не мусять показувати нічого про тестування."""
    reg, _ = _setup(active=False)
    _login(client, reg.user)
    html = client.get('/auth/account').get_data(as_text=True)
    assert 'тестування' not in html.lower()


# ---- перф-інваріант кабінету ------------------------------------------------

def _count_account_selects(client, user):
    """Скільки SELECT робить /auth/account для цього користувача."""
    from sqlalchemy import event

    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)

    counted = []

    def _count(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith('SELECT'):
            counted.append(statement)

    event.listen(db.engine, 'before_cursor_execute', _count)
    try:
        assert client.get('/auth/account').status_code == 200
    finally:
        event.remove(db.engine, 'before_cursor_execute', _count)
    return len(counted)


def _user_with_registrations(how_many):
    user = _user()
    for _ in range(how_many):
        reg, _quiz = _setup()
        reg.user_id = user.id
        db.session.flush()
    db.session.commit()
    return user


def test_cabinet_query_count_does_not_grow_with_registrations(client, app):
    """Кабінет не має дорожчати з кожним курсом користувача.

    Поштучний виклик `eligibility` давав +5 SELECT на реєстрацію: заміряно
    10/30/55 запитів на 1/5/10 курсів. Тобто сторінка тим повільніша, чим
    активніший учасник -- рівно навпаки до потрібного. `eligibility_map`
    вибирає все чотирма запитами незалежно від кількості рядків.

    Міряємо ПРИРІСТ, а не абсолютне число: постійна ціна сторінки залежить від
    речей поза цим тестом (наприклад від того, чи ввімкнена реферальна програма
    в налаштуваннях), і поріг на абсолют ламався б від чужих тестів.
    """
    few = _count_account_selects(client, _user_with_registrations(2))
    many = _count_account_selects(client, _user_with_registrations(10))

    assert many - few <= 4, (
        f'вісім додаткових реєстрацій дали +{many - few} SELECT '
        f'({few} -> {many}) -- схоже, повернувся N+1 у стані тестування'
    )


# ---- прогрес-бар без inline-стилю -------------------------------------------

def test_progress_uses_step_class_not_inline_style(client, app):
    """У проєкті діє No Inline Policy, а JS у цьому потоці свідомо немає.

    Ширина смуги задається кроковим класом. Раніше тут стояв style="width: N%" --
    єдиний inline-стиль серед публічних шаблонів проєкту.
    """
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    html = client.get(f'/quiz/attempt/{attempt.id}').get_data(as_text=True)
    assert 'style=' not in html.split('quiz-progress')[1][:400]
    assert 'quiz-progress__fill--0' in html      # жодної відповіді
    assert 'role="progressbar"' in html
    assert 'aria-valuemax="10"' in html


def test_progress_class_follows_answers(client, app):
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    for position in range(3):
        client.post(f'/quiz/attempt/{attempt.id}/answer', data={
            'position': str(position),
            'question_id': str(attempt.question_ids[position]),
            'choice': '1', 'direction': 'next',
        })

    html = client.get(f'/quiz/attempt/{attempt.id}').get_data(as_text=True)
    assert 'quiz-progress__fill--30' in html
    assert 'aria-valuenow="3"' in html


def test_all_answered_opens_review(client, app):
    """Повернення за старим посиланням, коли відповіді вже є на все.

    Раніше показувалось питання 1, і кнопку «Завершити» треба було шукати
    десятьма кліками.
    """
    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)

    resp = client.get(f'/quiz/attempt/{attempt.id}')
    assert resp.status_code == 302
    assert '/review' in resp.headers['Location']


def test_done_does_not_promise_email_that_was_not_sent(client, app, no_pdf,
                                                      monkeypatch):
    """Сторінка привітання не має обіцяти лист, якого не було."""
    from app.services.email_service import EmailService

    monkeypatch.setattr(
        EmailService, 'send_certificate',
        staticmethod(lambda cert: (_ for _ in ()).throw(RuntimeError('SMTP'))))

    reg, _ = _setup(bank=10, per_attempt=10, passing=8)
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    _answer_all(client, attempt, 10)
    client.post(f'/quiz/attempt/{attempt.id}/submit')

    html = client.get(f'/quiz/{reg.id}/done').get_data(as_text=True)
    assert 'Копію надіслано' not in html
    assert 'завжди доступний у кабінеті' in html
