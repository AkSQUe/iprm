"""Адмінка тестування: білдер банку питань, реєстр, результати, розблокування.

Головне, що тут перевіряється -- round-trip білдера. Питання зберігаються не
через WTForms, а плоскими полями `question_N_*`, які парсить сервіс, тож
розходження між іменами у шаблоні та в парсері не зловив би жоден інший тест:
форма просто зберегла б порожній банк.
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

_event_numbers = count(3000000)

FULL_PROFILE = {
    'participant_type': 'doctor', 'middle_name': 'Іванович',
    'birth_date': datetime(1985, 3, 12).date(), 'education': '2010, НМУ',
    'workplace': 'Клініка', 'position': 'лікар', 'specializations': ['therapy'],
}


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'aq-{uuid4().hex[:6]}@test.com', 'password123',
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


def _course(event_num=None, cpd_points=12):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'aq-{uuid4().hex[:6]}',
        is_active=True, event_type='course', cpd_points=cpd_points,
        bpr_event_number=(event_num if event_num is not None
                          else str(next(_event_numbers))),
    )
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course):
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        start_date=datetime.now(timezone.utc) - timedelta(days=2),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _registration(inst, profile=True):
    user = User.create_with_password(
        f'p-{uuid4().hex[:6]}@test.com', 'password123',
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
        specialty='Терапія', workplace='Клініка', status='confirmed',
        payment_status='paid')
    db.session.add(reg)
    db.session.flush()
    return reg


def _builder_payload(questions=10, per_attempt=10, passing=8, active='y'):
    """Дані білдера так, як їх надсилає браузер."""
    data = {
        'questions_per_attempt': str(per_attempt),
        'passing_score': str(passing),
        'max_attempts': '3',
        'shuffle_answers': 'y',
    }
    if active:
        data['is_active'] = active
    for i in range(questions):
        data[f'question_{i}_id'] = ''
        data[f'question_{i}_text'] = f'Питання {i + 1}?'
        data[f'question_{i}_correct'] = '2'
        for j in range(4):
            data[f'question_{i}_answer_{j}_text'] = f'Варіант {j + 1}'
    return data


# ---- доступ -----------------------------------------------------------------

def test_quiz_pages_require_admin(client, app):
    course = _course()
    db.session.commit()
    for url in ('/admin/quizzes', f'/admin/courses/{course.id}/quiz'):
        resp = client.get(url)
        assert resp.status_code in (302, 401, 403), url


def test_non_admin_gets_403(client, app):
    user = User.create_with_password(
        f'u-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='U', last_name='U', email_confirmed=True)
    course = _course()
    db.session.flush()
    _login(client, user)
    assert client.get(f'/admin/courses/{course.id}/quiz').status_code == 403


# ---- реєстр -----------------------------------------------------------------

def test_registry_renders(client, admin):
    course = _course()
    _login(client, admin)
    html = client.get('/admin/quizzes').get_data(as_text=True)
    assert course.title in html


def test_registry_flags_missing_bpr_data(client, admin):
    """Курс без номера заходу БПР мусить бути видимо позначений."""
    _course(event_num='')
    _login(client, admin)
    html = client.get('/admin/quizzes').get_data(as_text=True)
    assert 'немає даних БПР' in html


def test_registry_search(client, admin):
    wanted = _course()
    other = _course()
    _login(client, admin)
    html = client.get(f'/admin/quizzes?q={wanted.title}').get_data(as_text=True)
    assert wanted.title in html
    assert other.title not in html


# ---- редактор ---------------------------------------------------------------

def test_editor_opens_without_creating_a_row(client, admin):
    """Окремої кнопки «створити тест» немає -- редактор відкривається завжди.

    Але рядок у БД з'являється лише при збереженні. Раніше редактор флашив
    новий тест уже на GET: рядок не переживав teardown сесії, зате `quiz.id`
    заповнювався, і шаблон малював кнопку «Видалити тест» для тесту, якого не
    існує -- клік вів у «Тест не знайдено».
    """
    course = _course()
    _login(client, admin)
    html = client.get(f'/admin/courses/{course.id}/quiz').get_data(as_text=True)

    assert 'Банк питань' in html
    assert 'Видалити тест' not in html
    assert CourseQuiz.query.filter_by(course_id=course.id).count() == 0


def test_delete_button_appears_only_for_saved_quiz(client, admin):
    course = _course()
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))

    html = client.get(f'/admin/courses/{course.id}/quiz').get_data(as_text=True)
    assert 'Видалити тест' in html


def test_first_save_creates_quiz(client, admin):
    course = _course()
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))
    assert CourseQuiz.query.filter_by(course_id=course.id).count() == 1


def test_editor_warns_when_bpr_missing(client, admin):
    course = _course(event_num='')
    inst = _instance(course)
    _login(client, admin)
    html = client.get(f'/admin/instances/{inst.id}/quiz').get_data(as_text=True)
    assert 'Тест не відкриється учасникам' in html


def test_builder_round_trip(client, admin):
    """Ключовий тест: імена полів у шаблоні збігаються з парсером сервісу."""
    course = _course()
    _login(client, admin)
    resp = client.post(f'/admin/courses/{course.id}/quiz',
                       data=_builder_payload(10), follow_redirects=True)
    assert resp.status_code == 200

    quiz = CourseQuiz.query.filter_by(course_id=course.id).one()
    assert quiz.bank_size == 10
    assert quiz.is_active is True
    assert quiz.is_ready is True

    question = quiz.questions[0]
    assert question.text == 'Питання 1?'
    assert len(question.answers) == 4
    assert question.correct_index == 2


def test_saved_quiz_is_resolvable_for_participant(client, admin):
    """Наскрізна перевірка: збережений в адмінці тест відкривається учаснику."""
    course = _course()
    inst = _instance(course)
    reg = _registration(inst)
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))

    assert quiz_service.eligibility(reg).status == quiz_service.AVAILABLE


def test_builder_updates_existing_question(client, admin):
    course = _course()
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))
    quiz = CourseQuiz.query.filter_by(course_id=course.id).one()
    kept = quiz.questions[0]

    data = _builder_payload(10)
    data['question_0_id'] = str(kept.id)
    data['question_0_text'] = 'Оновлене питання?'
    client.post(f'/admin/courses/{course.id}/quiz', data=data)

    db.session.expire_all()
    assert db.session.get(QuizQuestion, kept.id).text == 'Оновлене питання?'


def test_builder_deletes_removed_questions(client, admin):
    course = _course()
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))
    quiz = CourseQuiz.query.filter_by(course_id=course.id).one()

    client.post(f'/admin/courses/{course.id}/quiz',
                data=_builder_payload(3, per_attempt=3, passing=2))
    db.session.expire_all()
    assert db.session.get(CourseQuiz, quiz.id).bank_size == 3


def test_active_quiz_with_small_bank_warns(client, admin):
    """Увімкнути можна, але адмін мусить дізнатися, що тест не відкриється."""
    course = _course()
    _login(client, admin)
    resp = client.post(f'/admin/courses/{course.id}/quiz',
                       data=_builder_payload(3, per_attempt=10, passing=8),
                       follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert 'НЕ відкриється' in html
    assert CourseQuiz.query.filter_by(course_id=course.id).one().is_ready is False


def test_passing_score_above_questions_rejected(client, admin):
    """Відхилена форма не створює й не змінює нічого."""
    course = _course()
    _login(client, admin)
    resp = client.post(f'/admin/courses/{course.id}/quiz',
                       data=_builder_payload(10, per_attempt=10, passing=11))
    assert resp.status_code == 200      # форма повернулась з помилкою
    assert CourseQuiz.query.filter_by(course_id=course.id).count() == 0


def test_rejected_form_does_not_damage_saved_quiz(client, admin):
    course = _course()
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz',
                data=_builder_payload(10, per_attempt=10, passing=8))

    client.post(f'/admin/courses/{course.id}/quiz',
                data=_builder_payload(10, per_attempt=10, passing=11))

    db.session.expire_all()
    quiz = CourseQuiz.query.filter_by(course_id=course.id).one()
    assert quiz.passing_score == 8
    assert quiz.bank_size == 10


def test_question_translations_are_saved(client, admin):
    course = _course()
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))
    quiz = CourseQuiz.query.filter_by(course_id=course.id).one()
    question = quiz.questions[0]

    data = _builder_payload(10)
    data['question_0_id'] = str(question.id)
    data[f'trq__{question.id}__en__text'] = 'Question 1?'
    client.post(f'/admin/courses/{course.id}/quiz', data=data)

    db.session.expire_all()
    fresh = db.session.get(QuizQuestion, question.id)
    assert fresh.t('text', lang='en') == 'Question 1?'


# ---- перевизначення на проведенні ------------------------------------------

def test_instance_override_is_separate_quiz(client, admin):
    course = _course()
    inst = _instance(course)
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))
    client.post(f'/admin/instances/{inst.id}/quiz',
                data=_builder_payload(10, per_attempt=5, passing=4))

    assert CourseQuiz.query.filter_by(course_id=course.id).count() == 1
    override = CourseQuiz.query.filter_by(instance_id=inst.id).one()
    assert override.questions_per_attempt == 5
    assert quiz_service.resolve_quiz(inst) is override


def test_delete_quiz_keeps_attempts(client, admin, no_pdf):
    course = _course()
    inst = _instance(course)
    reg = _registration(inst)
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))
    quiz = CourseQuiz.query.filter_by(course_id=course.id).one()

    attempt = quiz_service.start_attempt(reg)
    attempt_id = attempt.id
    db.session.commit()

    client.post(f'/admin/quizzes/{quiz.id}/delete')
    db.session.expire_all()
    assert db.session.get(CourseQuiz, quiz.id) is None
    assert db.session.get(QuizAttempt, attempt_id) is not None


# ---- результати -------------------------------------------------------------

def test_results_page_renders(client, admin, no_pdf):
    course = _course()
    inst = _instance(course)
    reg = _registration(inst)
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))

    html = client.get(f'/admin/instances/{inst.id}/quiz-results').get_data(as_text=True)
    assert reg.user.full_name in html
    assert 'не починав' in html


def test_results_show_incomplete_profile(client, admin):
    course = _course()
    inst = _instance(course)
    _registration(inst, profile=False)
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))

    html = client.get(f'/admin/instances/{inst.id}/quiz-results').get_data(as_text=True)
    assert 'анкета не заповнена' in html


def test_results_never_leak_correct_answers(client, admin):
    """Сторінка адміна теж не має друкувати правильні відповіді у розмітку."""
    course = _course()
    inst = _instance(course)
    _registration(inst)
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))

    html = client.get(f'/admin/instances/{inst.id}/quiz-results').get_data(as_text=True)
    assert 'is_correct' not in html


# ---- спроби учасника --------------------------------------------------------

def test_unlock_grants_extra_attempts(client, admin, no_pdf):
    course = _course()
    inst = _instance(course)
    reg = _registration(inst)
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz',
                data=_builder_payload(10, per_attempt=10, passing=8))

    client.post(f'/admin/registrations/{reg.id}/quiz/unlock', data={'extra': '2'})
    db.session.expire_all()
    assert db.session.get(EventRegistration, reg.id).quiz_extra_attempts == 2


@pytest.mark.parametrize('extra', ['0', '-1', '99', 'abc', ''])
def test_unlock_rejects_bad_input(client, admin, extra):
    course = _course()
    inst = _instance(course)
    reg = _registration(inst)
    _login(client, admin)
    client.post(f'/admin/registrations/{reg.id}/quiz/unlock', data={'extra': extra})
    db.session.expire_all()
    assert db.session.get(EventRegistration, reg.id).quiz_extra_attempts == 0


def test_reset_clears_attempts_and_passed_state(client, admin, no_pdf):
    course = _course()
    inst = _instance(course)
    reg = _registration(inst)
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))

    attempt = quiz_service.start_attempt(reg)
    for qid in attempt.question_ids:
        question = db.session.get(QuizQuestion, qid)
        order = attempt.ordered_answer_indexes(qid)
        quiz_service.record_answer(attempt, qid, order.index(question.correct_index))
    quiz_service.submit_attempt(attempt)
    assert reg.quiz_passed_at is not None

    client.post(f'/admin/registrations/{reg.id}/quiz/reset')
    db.session.expire_all()
    fresh = db.session.get(EventRegistration, reg.id)
    assert fresh.quiz_passed_at is None
    assert QuizAttempt.query.filter_by(registration_id=reg.id).count() == 0


def test_reset_does_not_revoke_certificate(client, admin, no_pdf):
    """Обнулення тесту й відкликання сертифіката -- дві різні дії."""
    course = _course()
    inst = _instance(course)
    reg = _registration(inst)
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(10))

    attempt = quiz_service.start_attempt(reg)
    for qid in attempt.question_ids:
        question = db.session.get(QuizQuestion, qid)
        order = attempt.ordered_answer_indexes(qid)
        quiz_service.record_answer(attempt, qid, order.index(question.correct_index))
    quiz_service.submit_attempt(attempt)
    number = reg.certificate.number

    client.post(f'/admin/registrations/{reg.id}/quiz/reset')
    db.session.expire_all()
    fresh = db.session.get(EventRegistration, reg.id)
    assert fresh.certificate is not None
    assert fresh.certificate.number == number
    assert fresh.certificate.revoked is False


# ---- перф-інваріант реєстру -------------------------------------------------

def _count_registry_selects(client):
    from sqlalchemy import event

    counted = []

    def _count(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith('SELECT'):
            counted.append(statement)

    event.listen(db.engine, 'before_cursor_execute', _count)
    try:
        assert client.get('/admin/quizzes').status_code == 200
    finally:
        event.remove(db.engine, 'before_cursor_execute', _count)
    return len(counted)


def test_registry_query_count_does_not_grow_with_courses(client, admin):
    """Реєстр не має дорожчати з кожним курсом.

    Рядок реєстру обходить `course.instances`, щоб знайти перевизначення тесту,
    і без selectinload кожен курс тягнув окремий запит за своїми проведеннями.

    Міряємо ПРИРІСТ, а не абсолют: постійна ціна сторінки залежить від речей
    поза цим тестом, і поріг на абсолютне число ламався б від чужих тестів.

    Перший курс створюється ДО заміру базової лінії, і це не косметика.
    Порожній реєстр не виконує вторинних запитів selectinload узагалі --
    вантажити нічого. Тобто базова лінія на порожньому реєстрі не містить
    ПОСТІЙНОЇ ціни (material_kits, course_instances, material_reservations),
    і приріст показував +5 навіть там, де N+1 немає. Раніше цього не було
    видно лише тому, що попередні тести файлу лишали за собою закомічені
    курси й реєстр був непорожній -- тест перевіряв не те, що обіцяв.
    """
    from datetime import datetime, timedelta, timezone

    from app.models.course_instance import CourseInstance

    _login(client, admin)

    seed = _course()
    for _ in range(2):
        db.session.add(CourseInstance(
            course_id=seed.id, status='published', event_format='offline',
            start_date=datetime.now(timezone.utc) + timedelta(days=10)))
    db.session.commit()

    baseline = _count_registry_selects(client)

    for _ in range(8):
        course = _course()
        for _ in range(2):
            db.session.add(CourseInstance(
                course_id=course.id, status='published', event_format='offline',
                start_date=datetime.now(timezone.utc) + timedelta(days=10)))
    db.session.commit()

    grown = _count_registry_selects(client)
    assert grown - baseline <= 2, (
        f'вісім курсів з проведеннями дали +{grown - baseline} SELECT '
        f'({baseline} -> {grown}) -- схоже, повернувся N+1 по проведеннях'
    )


# --- пагінація сторінки результатів групи -------------------------------------
#
# Сторінка робила `.all()` і будувала батч-контекст на всю групу, а сортування й
# три лічильники рахувалися в Python із того самого списку. З пагінацією такі
# лічильники тихо перетворилися б на «скільки на цьому екрані», а сортування
# впорядковувало б кожну сторінку окремо -- тому і те, і те винесено в SQL.

def _quiz_with_bank(course, bank=2):
    quiz = CourseQuiz(course_id=course.id, questions_per_attempt=bank,
                      passing_score=1, max_attempts=3, shuffle_answers=False,
                      is_active=True)
    db.session.add(quiz)
    db.session.flush()
    for i in range(bank):
        db.session.add(QuizQuestion(
            quiz_id=quiz.id, text=f'Питання {i + 1}?', sort_order=i,
            answers=[{'text': 'a', 'is_correct': False},
                     {'text': 'b', 'is_correct': True},
                     {'text': 'c', 'is_correct': False},
                     {'text': 'd', 'is_correct': False}]))
    db.session.flush()
    return quiz


def test_results_page_paginates(client, admin, app):
    course = _course()
    inst = _instance(course)
    _quiz_with_bank(course)
    for _ in range(30):
        _registration(inst)
    _login(client, admin)

    html = client.get(
        f'/admin/instances/{inst.id}/quiz-results?per_page=25').get_data(as_text=True)
    assert 'admin-pagination' in html
    assert '1 / 2 (30)' in html


def test_counters_cover_the_whole_group_not_the_page(client, admin, app, no_pdf):
    """Головна пастка пагінації: «склали тест» мусить лишитись груповим."""
    course = _course()
    inst = _instance(course)
    _quiz_with_bank(course)
    regs = [_registration(inst) for _ in range(30)]

    # Складений тест лише в одного, і він навмисно НЕ на першій сторінці за
    # алфавітом -- сортування ставить тих, хто склав, першими.
    passed = regs[-1]
    passed.quiz_passed_at = datetime.now(timezone.utc)
    db.session.flush()

    _login(client, admin)
    page2 = client.get(
        f'/admin/instances/{inst.id}/quiz-results?per_page=25&page=2'
    ).get_data(as_text=True)

    # На другій сторінці учасника, що склав, немає -- але лічильники ті самі.
    assert '>30<' in page2, 'лічильник учасників став посторінковим'
    assert '>1<' in page2, 'лічильник складених став посторінковим'


def test_passed_participants_come_first_across_pages(client, admin, app):
    course = _course()
    inst = _instance(course)
    _quiz_with_bank(course)
    regs = [_registration(inst) for _ in range(30)]
    regs[-1].quiz_passed_at = datetime.now(timezone.utc)
    db.session.flush()
    winner_email = regs[-1].user.email

    _login(client, admin)
    page1 = client.get(
        f'/admin/instances/{inst.id}/quiz-results?per_page=25'
    ).get_data(as_text=True)
    assert winner_email in page1, 'сортування «склали спершу» не в SQL'


def test_empty_group_still_shows_the_quiz(client, admin, app):
    """Контекст із нуля реєстрацій не має перетворити наявний тест у «немає»."""
    course = _course()
    inst = _instance(course)
    _quiz_with_bank(course)
    _login(client, admin)

    html = client.get(f'/admin/instances/{inst.id}/quiz-results').get_data(as_text=True)
    assert 'Реєстрацій немає' in html
    assert 'Тест не налаштований' not in html


def test_instance_registrations_paginates(client, admin, app):
    course = _course()
    inst = _instance(course)
    for _ in range(30):
        _registration(inst)
    _login(client, admin)

    html = client.get(
        f'/admin/instances/{inst.id}/registrations?per_page=25').get_data(as_text=True)
    assert 'admin-pagination' in html
    assert '1 / 2 (30)' in html


def test_instance_registrations_stats_stay_group_wide(client, admin, app):
    course = _course()
    inst = _instance(course)
    for _ in range(30):
        _registration(inst)
    _login(client, admin)

    html = client.get(
        f'/admin/instances/{inst.id}/registrations?per_page=25&page=2'
    ).get_data(as_text=True)
    assert '>30<' in html, 'лічильник «всього» став посторінковим'


def test_pagination_keeps_the_filter(client, admin, app):
    course = _course()
    inst = _instance(course)
    for _ in range(30):
        _registration(inst)
    _login(client, admin)

    html = client.get(
        f'/admin/instances/{inst.id}/registrations?per_page=25&payment=paid'
    ).get_data(as_text=True)
    assert 'payment=paid' in html, 'посилання пагінації втрачає фільтр'


# --- вступний текст і дедлайн у білдері ---------------------------------------

def test_builder_saves_intro_and_deadline(client, admin, app):
    course = _course()
    _login(client, admin)
    payload = _builder_payload()
    payload['intro'] = 'Умови заходу.\nДругий рядок.'
    payload['deadline_days_after_end'] = '0'

    client.post(f'/admin/courses/{course.id}/quiz', data=payload,
                follow_redirects=True)
    quiz = CourseQuiz.query.filter_by(course_id=course.id).one()
    assert quiz.intro == 'Умови заходу.\nДругий рядок.'
    assert quiz.deadline_days_after_end == 0


def test_blank_intro_is_stored_as_null(client, admin, app):
    """Порожній textarea не має ставати рядком з пробілів: сторінка тесту
    вирішує «показувати чи ні» саме за наявністю значення."""
    course = _course()
    _login(client, admin)
    payload = _builder_payload()
    payload['intro'] = '   \n  '

    client.post(f'/admin/courses/{course.id}/quiz', data=payload,
                follow_redirects=True)
    assert CourseQuiz.query.filter_by(course_id=course.id).one().intro is None


def test_blank_deadline_means_no_limit(client, admin, app):
    course = _course()
    _login(client, admin)
    payload = _builder_payload()
    payload['deadline_days_after_end'] = ''

    client.post(f'/admin/courses/{course.id}/quiz', data=payload,
                follow_redirects=True)
    assert CourseQuiz.query.filter_by(
        course_id=course.id).one().deadline_days_after_end is None


def test_negative_deadline_is_rejected(client, admin, app):
    """«-1 день» закрив би тест до початку заходу."""
    course = _course()
    _login(client, admin)
    payload = _builder_payload()
    payload['deadline_days_after_end'] = '-1'

    client.post(f'/admin/courses/{course.id}/quiz', data=payload)
    assert CourseQuiz.query.filter_by(course_id=course.id).first() is None


def test_editor_shows_saved_values(client, admin, app):
    course = _course()
    _login(client, admin)
    payload = _builder_payload()
    payload['intro'] = 'Текст-маркер вступу'
    payload['deadline_days_after_end'] = '3'
    client.post(f'/admin/courses/{course.id}/quiz', data=payload,
                follow_redirects=True)

    html = client.get(f'/admin/courses/{course.id}/quiz').get_data(as_text=True)
    assert 'Текст-маркер вступу' in html
    assert 'value="3"' in html


def test_intro_has_language_tabs(client, admin, app):
    """Сторінку тесту читають трьома мовами, тож вступ мусить перекладатись."""
    course = _course()
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(),
                follow_redirects=True)
    quiz = CourseQuiz.query.filter_by(course_id=course.id).one()

    html = client.get(f'/admin/courses/{course.id}/quiz').get_data(as_text=True)
    assert f'trqz__{quiz.id}' in html


def test_intro_translation_is_saved_and_served(client, admin, app):
    course = _course()
    _login(client, admin)
    client.post(f'/admin/courses/{course.id}/quiz', data=_builder_payload(),
                follow_redirects=True)
    quiz = CourseQuiz.query.filter_by(course_id=course.id).one()

    payload = _builder_payload()
    payload['intro'] = 'Український вступ'
    # Порядок сегментів задає `_i18n_tabs.panes`: prefix__lang__field.
    payload[f'trqz__{quiz.id}__en__intro'] = 'English intro'
    client.post(f'/admin/courses/{course.id}/quiz', data=payload,
                follow_redirects=True)

    db.session.expire_all()
    quiz = CourseQuiz.query.filter_by(course_id=course.id).one()
    assert quiz.t('intro') == 'Український вступ'
    assert quiz.t('intro', 'en') == 'English intro'
