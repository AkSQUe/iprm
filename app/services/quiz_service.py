"""Тестування учасників: допуск, спроби, оцінювання, автовидача сертифіката.

Уся логіка тут; маршрути лишаються тонкими. `eligibility()` -- єдине джерело
правди про допуск: ним керуються і кабінет, і гейти маршрутів, і діагностика в
адмінці. Інакше три різні місця з трьома трохи різними умовами розійшлися б, і
учасник бачив би кнопку, яка веде в помилку.

Сервіс повертає СТАТУСИ, а не готові тексти: підписи й посилання живуть у
шаблонах, де є `url_for` і контекст мови.

Публічний API:
  * resolve_quiz(instance) -> CourseQuiz | None
  * eligibility(registration) -> Eligibility
  * attempts_left(registration, quiz) -> int
  * start_attempt(registration) -> QuizAttempt
  * record_answer(attempt, question_id, position) -> bool
  * submit_attempt(attempt) -> QuizAttempt
  * award_and_issue(registration) -> Certificate | None
  * extract_questions_from_form(form_data) / save_questions_for_quiz(quiz, data)
"""
import logging
import random
from typing import NamedTuple

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.course_quiz import ANSWERS_PER_QUESTION, CourseQuiz, QuizQuestion
from app.models.mixins import utcnow
from app.models.quiz_attempt import QuizAttempt
from app.utils import ensure_utc

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


# ---- Статуси допуску ----
# Порядок перевірок у eligibility() навмисний, див. коментарі там.
NO_QUIZ = 'no_quiz'                        # тесту для цього заходу немає
CANCELLED = 'cancelled'                    # реєстрацію скасовано
NOT_PAID = 'not_paid'                      # участь не оплачена
NOT_STARTED = 'not_started'                # захід ще не розпочався
PASSED = 'passed'                          # уже склав
IN_PROGRESS = 'in_progress'                # є незавершена спроба -- продовжити
QUIZ_NOT_READY = 'quiz_not_ready'          # банк питань недостатній/зіпсований
BPR_NOT_CONFIGURED = 'bpr_not_configured'  # немає номерів/балів БПР
PROFILE_INCOMPLETE = 'profile_incomplete'  # анкета МОЗ №725 не заповнена
ATTEMPTS_EXHAUSTED = 'attempts_exhausted'  # спроби вичерпано
AVAILABLE = 'available'                    # можна починати

# Статуси, за яких учасник може працювати з тестом просто зараз.
ACTIONABLE = (AVAILABLE, IN_PROGRESS)


class Eligibility(NamedTuple):
    """Чому тест доступний або ні -- з усім, що потрібно для показу."""
    status: str
    quiz: CourseQuiz = None
    attempt: QuizAttempt = None
    attempts_left: int = 0
    missing_fields: tuple = ()

    @property
    def is_actionable(self):
        return self.status in ACTIONABLE


class BatchContext(NamedTuple):
    """Заздалегідь вибрані дані для набору реєстрацій -- проти N+1.

    `eligibility()` приймає цей контекст і бере все з нього замість власних
    запитів. ПРАВИЛА при цьому лишаються в одному місці: контекст постачає
    дані, а не рішення. Друга реалізація умов допуску розійшлася б із першою --
    цю помилку в підсистемі вже виправляли (оцінювання жило у двох місцях).
    """
    quiz_by_instance: dict
    quiz_by_course: dict
    finished_counts: dict
    unfinished: dict
    provider_ok: bool


def build_batch_context(registrations):
    """Чотири запити на будь-яку кількість реєстрацій."""
    from app.models.site_settings import SiteSettings
    from sqlalchemy import func as sa_func
    from sqlalchemy.orm import selectinload

    registrations = list(registrations)
    reg_ids = [r.id for r in registrations]
    instance_ids = {r.instance_id for r in registrations if r.instance_id}
    course_ids = {
        r.instance.course_id for r in registrations
        if r.instance is not None and r.instance.course_id
    }

    quizzes = []
    if instance_ids or course_ids:
        quizzes = (
            CourseQuiz.query
            .options(selectinload(CourseQuiz.questions))
            .filter(
                CourseQuiz.instance_id.in_(instance_ids or [0])
                | CourseQuiz.course_id.in_(course_ids or [0])
            )
            .all()
        )

    finished_counts = {}
    unfinished = {}
    if reg_ids:
        finished_counts = dict(
            db.session.query(
                QuizAttempt.registration_id, sa_func.count(QuizAttempt.id),
            )
            .filter(QuizAttempt.registration_id.in_(reg_ids),
                    QuizAttempt.submitted_at.isnot(None))
            .group_by(QuizAttempt.registration_id)
            .all()
        )
        # Незавершена спроба на реєстрацію одна (нову не почати, доки є ця),
        # тож простий dict без вибору «найсвіжішої» тут достатній.
        for attempt in (
            QuizAttempt.query
            .filter(QuizAttempt.registration_id.in_(reg_ids),
                    QuizAttempt.submitted_at.is_(None))
            .order_by(QuizAttempt.attempt_number)
            .all()
        ):
            unfinished[attempt.registration_id] = attempt

    return BatchContext(
        quiz_by_instance={q.instance_id: q for q in quizzes if q.instance_id},
        quiz_by_course={q.course_id: q for q in quizzes if q.course_id},
        finished_counts=finished_counts,
        unfinished=unfinished,
        provider_ok=bool((SiteSettings.get().bpr_provider_number or '').strip()),
    )


def eligibility_map(registrations):
    """{registration_id: Eligibility} без N+1.

    Кабінет робив +5 SELECT на кожну реєстрацію (заміряно: 10/30/55 запитів на
    1/5/10 реєстрацій). Навіть заходи без тесту платили два запити.
    """
    registrations = list(registrations)
    if not registrations:
        return {}
    context = build_batch_context(registrations)
    return {reg.id: eligibility(reg, context=context) for reg in registrations}


def resolve_quiz(instance, context=None):
    """Чинний тест для проведення: перевизначення проведення -> тест курсу.

    Неактивне перевизначення НЕ блокує тест курсу: воно ще чернетка, і поки
    адмін його готує, група мусить складати за базовим набором.
    """
    if instance is None:
        return None

    if context is not None:
        override = context.quiz_by_instance.get(instance.id)
    else:
        override = CourseQuiz.query.filter_by(instance_id=instance.id).first()
    if override is not None and override.is_active:
        return override

    if instance.course_id is None:
        return None
    if context is not None:
        quiz = context.quiz_by_course.get(instance.course_id)
    else:
        quiz = CourseQuiz.query.filter_by(course_id=instance.course_id).first()
    return quiz if quiz is not None and quiz.is_active else None


def public_quiz_for_course(course):
    """Тест курсу для ПУБЛІЧНОЇ сторінки або None.

    Віддаємо лише тест, який реально можна скласти й за який реально видадуть
    сертифікат: увімкнений, з достатнім банком і з заповненими даними БПР.
    Інакше блок «Умови отримання сертифікату» обіцяв би те, чого система не
    виконує -- саме через це партіал `_event_certificate.html` і прожив без
    діла, обіцяючи тестування, якого не існувало.

    Перевизначення на проведеннях тут свідомо не враховуємо: сторінка курсу
    описує курс загалом, і різні набори на різних датах на ній не описати.
    """
    from app.models.site_settings import SiteSettings

    if course is None:
        return None
    quiz = CourseQuiz.query.filter_by(course_id=course.id).first()
    if quiz is None or not quiz.is_active or not quiz.is_ready:
        return None
    if not (SiteSettings.get().bpr_provider_number or '').strip():
        return None
    if not (course.bpr_event_number or '').strip() or not course.cpd_points:
        return None
    return quiz


def _bpr_is_configured(instance, context=None):
    """Чи вистачає даних, щоб видати сертифікат за цей захід.

    Перевіряємо ДО того, як пустити людину в тест. Інакше вона склала б його і
    отримала помилку замість сертифіката: `issue_certificate` кидає ValueError
    без номера провайдера чи номера заходу БПР. У проді 10 з 13 курсів цих
    номерів не мають, тож випадок не гіпотетичний.
    """
    from app.models.site_settings import SiteSettings

    course = instance.course if instance is not None else None
    if course is None:
        return False
    provider_ok = (
        context.provider_ok if context is not None
        else bool((SiteSettings.get().bpr_provider_number or '').strip())
    )
    if not provider_ok:
        return False
    if not (course.bpr_event_number or '').strip():
        return False
    # Бали друкуються на сертифікаті; без них документ виходить порожнім.
    return bool(instance.effective_cpd_points)


def _unfinished_attempt(registration, context=None):
    if context is not None:
        return context.unfinished.get(registration.id)
    return (
        QuizAttempt.query
        .filter_by(registration_id=registration.id)
        .filter(QuizAttempt.submitted_at.is_(None))
        .order_by(QuizAttempt.attempt_number.desc())
        .first()
    )


def _finished_attempts_count(registration, context=None):
    """Витрачені спроби -- лише завершені.

    Незавершена спроба не рахується: закрита вкладка чи втрачений зв'язок не
    мусять з'їдати одну з трьох спроб, людина повертається й продовжує ту саму.
    """
    if context is not None:
        return context.finished_counts.get(registration.id, 0)
    return (
        QuizAttempt.query
        .filter_by(registration_id=registration.id)
        .filter(QuizAttempt.submitted_at.isnot(None))
        .count()
    )


def attempts_left(registration, quiz, context=None):
    if quiz is None:
        return 0
    allowed = quiz.max_attempts + (registration.quiz_extra_attempts or 0)
    return max(allowed - _finished_attempts_count(registration, context), 0)


def eligibility(registration, context=None):
    """Чи може учасник проходити тест зараз -- і якщо ні, то чому.

    `context` -- необов'язковий `BatchContext` для набору реєстрацій: правила
    ті самі, лише дані вже вибрані (див. `eligibility_map`).
    """
    instance = registration.instance
    quiz = resolve_quiz(instance, context)

    # Тесту немає -- у кабінеті блок тестування взагалі не показуємо, тож ця
    # перевірка стоїть перед усіма іншими: казати «захід не розпочався» про
    # захід без тесту було б дезінформацією.
    if quiz is None:
        return Eligibility(NO_QUIZ)

    if registration.status == 'cancelled':
        return Eligibility(CANCELLED, quiz=quiz)

    if registration.payment_status != 'paid':
        return Eligibility(NOT_PAID, quiz=quiz)

    start = ensure_utc(instance.start_date if instance else None)
    if start is None or start > utcnow():
        return Eligibility(NOT_STARTED, quiz=quiz)

    if registration.quiz_passed_at is not None:
        return Eligibility(PASSED, quiz=quiz)

    # Незавершена спроба -- перед рештою заборон: спробу, яку вже почали, треба
    # дати завершити, навіть якщо тим часом змінились налаштування чи анкета.
    unfinished = _unfinished_attempt(registration, context)
    if unfinished is not None:
        return Eligibility(
            IN_PROGRESS, quiz=quiz, attempt=unfinished,
            attempts_left=attempts_left(registration, quiz, context),
        )

    if not quiz.is_ready:
        return Eligibility(QUIZ_NOT_READY, quiz=quiz)

    if not _bpr_is_configured(instance, context):
        return Eligibility(BPR_NOT_CONFIGURED, quiz=quiz)

    profile = registration.user.medical_profile if registration.user else None
    if profile is None or not profile.is_complete:
        return Eligibility(
            PROFILE_INCOMPLETE, quiz=quiz,
            missing_fields=tuple(profile.missing_fields if profile else ()),
        )

    left = attempts_left(registration, quiz, context)
    if left <= 0:
        return Eligibility(ATTEMPTS_EXHAUSTED, quiz=quiz)

    return Eligibility(AVAILABLE, quiz=quiz, attempts_left=left)


# ---- Проходження ----

def start_attempt(registration):
    """Почати спробу (або повернути незавершену).

    Набір питань і порядок варіантів фіксуються ТУТ і живуть у рядку спроби:
    інакше кожне перезавантаження сторінки перемішувало б тест, і людина, яка
    відповіла на сім із десяти, побачила б інший.
    """
    state = eligibility(registration)
    if state.status == IN_PROGRESS:
        return state.attempt
    if state.status != AVAILABLE:
        raise ValueError(f'Тест недоступний: {state.status}')

    quiz = state.quiz
    pool = [q for q in quiz.active_questions if q.is_valid]
    chosen = random.sample(pool, quiz.questions_per_attempt)

    answer_order = {}
    for question in chosen:
        positions = list(range(len(question.answers or [])))
        if quiz.shuffle_answers:
            random.shuffle(positions)
        answer_order[str(question.id)] = positions

    attempt = QuizAttempt(
        registration_id=registration.id,
        user_id=registration.user_id,
        quiz_id=quiz.id,
        attempt_number=_finished_attempts_count(registration) + 1,
        question_ids=[q.id for q in chosen],
        answer_order=answer_order,
        submitted_answers={},
        total=len(chosen),
        passing_score=quiz.passing_score,
        started_at=utcnow(),
    )
    db.session.add(attempt)
    try:
        db.session.flush()
    except IntegrityError:
        # Подвійне натискання «Почати тест» (на мобільному -- звична річ): два
        # запити не бачать чужої незакоміченої спроби і беруть один
        # attempt_number. Unique-констрейнт це ловить, але 500 замість тесту
        # виглядав би як зламаний сайт. Віддаємо ту спробу, що виграла гонку.
        db.session.rollback()
        existing = _unfinished_attempt(registration)
        if existing is not None:
            logger.info(
                'Concurrent quiz start for reg=%s -- reusing attempt %s',
                registration.id, existing.id,
            )
            return existing
        raise

    logger.info(
        'Quiz attempt %d started: reg=%s quiz=%s questions=%d',
        attempt.attempt_number, registration.id, quiz.id, attempt.total,
    )
    return attempt


def record_answer(attempt, question_id, position):
    """Зберегти одну відповідь. False -- вхідні дані не стосуються цієї спроби.

    Пишемо інкрементально, щоб закрита вкладка не з'їдала спробу. Значення --
    ПОЗИЦІЯ у перемішаному списку, а не індекс варіанта: клієнт про справжні
    індекси не знає й не мусить.
    """
    if attempt.is_finished:
        return False
    try:
        question_id = int(question_id)
        position = int(position)
    except (TypeError, ValueError):
        return False
    if question_id not in (attempt.question_ids or []):
        return False
    if not 0 <= position < len(attempt.ordered_answer_indexes(question_id)):
        return False

    # Новий dict, а не мутація: інакше SQLAlchemy не побачить зміни JSON-колонки
    # (той самий підхід, що в TranslatableMixin.set_translation).
    answers = dict(attempt.submitted_answers or {})
    answers[str(question_id)] = position
    attempt.submitted_answers = answers
    return True


def question_results(attempt):
    """Результат по кожному питанню спроби: [(номер, question_id, зараховано)].

    Єдине місце, де вирішується «зараховано чи ні». І оцінювання, і показ
    незарахованих номерів на сторінці результату йдуть звідси: доки це були дві
    окремі реалізації, вони неминуче розійшлися б на першій правці.
    """
    ids = attempt.question_ids or []
    questions = {
        q.id: q for q in QuizQuestion.query.filter(QuizQuestion.id.in_(ids or [0]))
    }

    results = []
    for position, question_id in enumerate(ids):
        question = questions.get(question_id)
        if question is None:
            # Адмін видалив питання, поки людина проходила тест. Перевірити
            # відповідь уже неможливо, і карати за це учасника нема за що: він
            # не є актором цієї зміни, а спроб у нього лише три.
            logger.warning(
                'Quiz question %s vanished mid-attempt %s -- counted as correct',
                question_id, attempt.id,
            )
            results.append((position + 1, question_id, True))
            continue

        chosen = attempt.chosen_position(question_id)
        order = attempt.ordered_answer_indexes(question_id)
        correct = (
            chosen is not None
            and 0 <= chosen < len(order)
            and order[chosen] == question.correct_index
        )
        results.append((position + 1, question_id, correct))
    return results


def grade_attempt(attempt):
    """Скільки правильних у спробі. Не змінює стан -- лише рахує."""
    return sum(1 for _number, _qid, correct in question_results(attempt) if correct)


def wrong_numbers(attempt):
    """Номери незарахованих питань -- БЕЗ правильних відповідей.

    Показуємо на результаті, щоб людина знала, куди дивитись, але не
    перетворюємо другу й третю спроби на формальність.
    """
    return [number for number, _qid, correct in question_results(attempt)
            if not correct]


def submit_attempt(attempt):
    """Завершити й оцінити спробу; при успіху -- видати сертифікат.

    Ідемпотентна: повторний submit уже завершеної спроби нічого не змінює
    (кнопку «Завершити» легко натиснути двічі).
    """
    if attempt.is_finished:
        return attempt

    attempt.score = grade_attempt(attempt)
    attempt.passed = attempt.score >= attempt.passing_score
    attempt.submitted_at = utcnow()

    registration = attempt.registration
    if attempt.passed and registration.quiz_passed_at is None:
        registration.quiz_passed_at = attempt.submitted_at

    # Комітимо результат ДО видачі, а не разом із нею. Видача малює PDF і пише
    # ще два рядки; якби вона впала на рівні БД, сесія лишилася б зламаною, і
    # спільний коміт забрав би із собою зафіксований результат тесту -- людина
    # втратила б і спробу, і складений тест.
    db.session.commit()

    audit_logger.info(
        'Quiz attempt %d submitted: reg=%s score=%d/%d passed=%s',
        attempt.attempt_number, registration.id, attempt.score,
        attempt.total, attempt.passed,
    )

    if attempt.passed:
        award_and_issue(registration)
    return attempt


def _email_certificate(certificate):
    """Надіслати сертифікат листом -- best-effort, як в адмінському шляху.

    Автовидача без цього кроку віддавала сертифікат лише в кабінет, а сторінка
    привітання при цьому обіцяла «копію надіслано на вашу пошту». Ручна видача
    (admin/routes_registrations.py) лист надсилає окремим викликом -- тут його
    просто не було.

    Провал не відкочує видачу: сертифікат уже закомічений, і лист можна
    переслати з картки реєстрації. Відкочуємо лише невдалий INSERT у email_logs,
    інакше сесія лишилась би зламаною для решти запиту.
    """
    from app.services.email_service import EmailService

    try:
        EmailService.send_certificate(certificate)
        return True
    except Exception:
        db.session.rollback()
        logger.exception(
            'Failed to email auto-issued certificate %s', certificate.number)
        return False


def certificate_email_sent(registration):
    """Чи справді пішов лист із сертифікатом по цій реєстрації.

    Питаємо журнал, а не прапорець у пам'яті: сторінка привітання рендериться
    ІНШИМ запитом (submit -> result -> done), тож стан відправки має бути
    відновлюваним. Заодно це враховує повторне надсилання з адмінки.
    """
    from app.models.email_log import EmailLog

    return db.session.query(EmailLog.id).filter(
        EmailLog.registration_id == registration.id,
        EmailLog.trigger == 'certificate',
        EmailLog.status == 'sent',
    ).first() is not None


def award_and_issue(registration):
    """Нарахувати бали, позначити присутність і видати сертифікат.

    Успішний тест -- це і є підтвердження участі, тож `attended` і
    `cpd_points_awarded` виставляємо тут, а не лишаємо адміну: інакше бали БПР
    залежали б від ручної роботи, а сертифікат уже був би на руках. Побічно це
    відправляє партнерський вебхук `registration.attended` -- через наявний
    SQLAlchemy-лістенер, саме собою.

    Повертає None, якщо видати не вдалося: присутність і бали при цьому вже
    збережені, а сертифікат адмін видасть вручну, заповнивши дані БПР.
    """
    from app.services import certificate_service

    instance = registration.instance
    registration.attended = True
    # Статус теж переводимо, як це робить ручна відмітка присутності
    # (admin/routes_registrations.py -> registration_attendance). Інакше два
    # шляхи «участь відбулась» дають різні стани: кабінет показував би
    # «Підтверджено» людині з сертифікатом на руках, а адмінський фільтр
    # «без сертифіката» (status='completed') таких реєстрацій не бачив би.
    if registration.status != 'cancelled':
        registration.status = 'completed'
    if registration.cpd_points_awarded is None:
        registration.cpd_points_awarded = (
            instance.effective_cpd_points if instance else None
        )
    # Окремим комітом, до видачі: інакше провал видачі на рівні БД забрав би
    # разом із собою присутність і нараховані бали.
    db.session.commit()

    try:
        certificate = certificate_service.issue_certificate(registration)
    except Exception:
        # Сесія після збою на рівні БД лишається зламаною -- відкочуємо, щоб
        # наступний запит не наткнувся на неї. Результат тесту, присутність і
        # бали вже закомічені й від цього не страждають.
        db.session.rollback()
        logger.exception(
            'Auto-issue failed after passed quiz: reg=%s', registration.id)
        return None

    _email_certificate(certificate)

    audit_logger.info(
        'Certificate %s auto-issued after quiz: reg=%s',
        certificate.number, registration.id,
    )
    return certificate


# ---- Банк питань: форма <-> БД ----

def extract_questions_from_form(form_data):
    """Розпарсити плоскі поля білдера у структурований список.

    Формат полів (як у «блоках програми», єдиному репітері проєкту):
      question_N_id, question_N_text,
      question_N_answer_M_text, question_N_correct

    Питання без тексту пропускаються. `question_N_correct` -- номер правильного
    варіанта (M). Невалідний id трактуємо як None: питання створиться заново,
    але форма не впаде на 500.
    """
    questions = []
    idx = 0
    while f'question_{idx}_text' in form_data:
        text = (form_data.get(f'question_{idx}_text') or '').strip()
        if text:
            raw_id = form_data.get(f'question_{idx}_id') or ''
            question_id = None
            if raw_id:
                try:
                    question_id = int(raw_id)
                except (TypeError, ValueError):
                    logger.warning(
                        'Invalid question_%d_id=%r -- ignoring, will create new',
                        idx, raw_id,
                    )
            try:
                correct = int(form_data.get(f'question_{idx}_correct'))
            except (TypeError, ValueError):
                correct = None

            answers = []
            for pos in range(ANSWERS_PER_QUESTION):
                answers.append({
                    'text': (form_data.get(
                        f'question_{idx}_answer_{pos}_text') or '').strip(),
                    'is_correct': correct == pos,
                })

            questions.append({
                'id': question_id,
                'text': text,
                'answers': answers,
            })
        idx += 1
    return questions


def save_questions_for_quiz(quiz, questions_data):
    """Синхронізувати банк питань зі структурованим списком.

    Наявні (за id) оновлюються, нові створюються, відсутні видаляються --
    так само, як `course_service.save_program_blocks_for_course`.
    """
    by_id = {q.id: q for q in quiz.questions}
    seen_ids = set()

    for idx, data in enumerate(questions_data):
        question = by_id.get(data.get('id'))
        if question is not None:
            question.text = data['text']
            question.answers = data['answers']
            question.sort_order = idx
            seen_ids.add(question.id)
        else:
            db.session.add(QuizQuestion(
                quiz=quiz,
                text=data['text'],
                answers=data['answers'],
                sort_order=idx,
            ))

    # Видаляємо через колекцію, а не db.session.delete: cascade delete-orphan
    # прибере рядок, а `quiz.questions` у пам'яті лишиться правдивим. З прямим
    # delete() колекція показувала б уже видалені питання до кінця запиту --
    # і валідація готовності тесту рахувала б їх.
    for old_id in set(by_id) - seen_ids:
        quiz.questions.remove(by_id[old_id])


def validation_errors(quiz):
    """Людські помилки готовності тесту -- для адмінки.

    Окремо від `CourseQuiz.is_ready`: там булеве «готовий», тут -- перелік того,
    що саме треба виправити.
    """
    errors = []
    questions = quiz.active_questions
    if len(questions) < quiz.questions_per_attempt:
        errors.append(
            f'У банку {len(questions)} активних питань, а на спробу потрібно '
            f'{quiz.questions_per_attempt}.'
        )
    for idx, question in enumerate(questions, start=1):
        if len(question.answers or []) != ANSWERS_PER_QUESTION:
            errors.append(
                f'Питання {idx}: має бути рівно {ANSWERS_PER_QUESTION} '
                f'варіантів, зараз {len(question.answers or [])}.'
            )
        elif question.correct_index is None:
            errors.append(
                f'Питання {idx}: треба позначити рівно одну правильну відповідь.'
            )
    return errors


def _build_view_model(attempt, position, question, total):
    """Представлення одного питання. Єдине місце, що будує його для учасника.

    Правильність відповіді НЕ потрапляє у результат -- взагалі, тож витік
    `is_correct` у HTML неможливий за побудовою.
    """
    texts = question.answer_texts()
    order = attempt.ordered_answer_indexes(question.id)
    return {
        'question_id': question.id,
        'position': position,
        'number': position + 1,
        'total': total,
        'text': question.t('text'),
        # Варіанти вже у порядку цієї спроби; клієнт бачить лише позиції.
        'answers': [
            {'position': pos, 'text': texts[original]}
            for pos, original in enumerate(order)
            if 0 <= original < len(texts)
        ],
        'chosen': attempt.chosen_position(question.id),
    }


def attempt_view_model(attempt, position):
    """Дані для показу одного питання спроби (None -- позиція поза межами)."""
    question_ids = attempt.question_ids or []
    if not 0 <= position < len(question_ids):
        return None
    question = db.session.get(QuizQuestion, question_ids[position])
    if question is None:
        return None
    return _build_view_model(attempt, position, question, len(question_ids))


def attempt_view_models(attempt):
    """Представлення ВСІХ питань спроби -- одним запитом.

    Сторінка звірки раніше кликала `attempt_view_model` у циклі, тобто робила
    окремий SELECT на кожне питання (десять на сторінку). Видалені питання
    просто пропускаються: сама звірка нічого не оцінює.
    """
    ids = attempt.question_ids or []
    if not ids:
        return []
    questions = {
        q.id: q for q in QuizQuestion.query.filter(QuizQuestion.id.in_(ids))
    }
    return [
        _build_view_model(attempt, position, questions[qid], len(ids))
        for position, qid in enumerate(ids) if qid in questions
    ]
