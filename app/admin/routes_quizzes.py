"""Адмінка тестування: реєстр тестів, білдер питань, результати, розблокування.

Тест живе на курсі (базовий набір) або на проведенні (перевизначення), тож
редактор один, а входів до нього два. Окремої кнопки «створити тест» немає:
редактор відкривається завжди, а рядок у БД з'являється при першому збереженні.

Банк питань не входить у WTForms-форму: 10+ питань по 4 варіанти -- це репітер
із динамічною кількістю полів. У цьому проєкті такі речі робляться плоскими
іменами `question_N_*` і парсяться сервісом -- так само, як «блоки програми»
курсу (єдиний інший репітер тут).
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import contains_eager, joinedload, selectinload

from app.admin import _listing, admin_bp
from app.admin._helpers import try_commit
from app.rbac import permission_required
from app.admin.forms import CourseQuizForm
from app.admin.routes_translations import apply_inline_translations
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_quiz import CourseQuiz
from app.models.quiz_attempt import QuizAttempt
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import quiz_service

audit_logger = logging.getLogger('audit')


def _quiz_for(course=None, instance=None):
    """Наявний тест або НОВИЙ незбережений об'єкт (без id, не в сесії).

    Раніше новий тест тут одразу додавався і флашився. На GET це не давало
    рядка в БД (сесія відкочується при teardown), зате `quiz.id` уже був
    заповнений -- і шаблон малював кнопку «Видалити тест» для тесту, якого не
    існує. Клік по ній вів у «Тест не знайдено».

    Тепер об'єкт без id живе лише в пам'яті, а в сесію потрапляє тільки при
    збереженні (`_save_editor`).
    """
    if instance is not None:
        quiz = CourseQuiz.query.filter_by(instance_id=instance.id).first()
    else:
        quiz = CourseQuiz.query.filter_by(course_id=course.id).first()
    if quiz is not None:
        return quiz
    return CourseQuiz(
        course_id=course.id if instance is None else None,
        instance_id=instance.id if instance is not None else None,
    )


def _apply_question_translations(quiz):
    """Переклади питань -- окремим префіксом на сутність.

    Викликати ПІСЛЯ save_questions_for_quiz: щойно додане питання отримує id
    лише там, а до того мовних полів для нього у формі просто немає. Той самий
    порядок, що для блоків програми в routes_courses.
    """
    for question in quiz.questions:
        apply_inline_translations(question, prefix=f'trq__{question.id}')


def _render_editor(quiz, course, instance, form):
    errors = quiz_service.validation_errors(quiz) if quiz.id else []
    return render_template(
        'admin/quiz_edit.html',
        quiz=quiz,
        course=course,
        instance=instance,
        form=form,
        validation_errors=errors,
        bpr_ready=quiz_service._bpr_is_configured(instance) if instance else None,
    )


def _save_editor(quiz, redirect_endpoint, **redirect_kwargs):
    """Спільна обробка POST для обох входів у редактор."""
    form = CourseQuizForm()
    if not form.validate_on_submit():
        return None, form

    quiz.questions_per_attempt = form.questions_per_attempt.data
    quiz.passing_score = form.passing_score.data
    quiz.max_attempts = form.max_attempts.data
    quiz.shuffle_answers = bool(form.shuffle_answers.data)
    quiz.is_active = bool(form.is_active.data)
    quiz.intro = (form.intro.data or '').strip() or None
    quiz.deadline_days_after_end = form.deadline_days_after_end.data
    if quiz.id is None:
        db.session.add(quiz)

    questions = quiz_service.extract_questions_from_form(request.form)
    quiz_service.save_questions_for_quiz(quiz, questions)
    db.session.flush()
    _apply_question_translations(quiz)
    # Переклад вступного тексту -- після flush, з тієї самої причини, що й у
    # питань: до нього тест може ще не мати id.
    apply_inline_translations(quiz, prefix=f'trqz__{quiz.id}')

    if try_commit(log_context=f'quiz_save id={quiz.id}'):
        audit_logger.info(
            'Admin %s saved quiz %s (%d questions, active=%s)',
            current_user.email, quiz.id, len(quiz.questions), quiz.is_active,
        )
        remaining = quiz_service.validation_errors(quiz)
        if quiz.is_active and remaining:
            flash('Збережено, але тест НЕ відкриється: ' + ' '.join(remaining),
                  'warning')
        else:
            flash('Тест збережено.', 'success')
        return redirect(url_for(redirect_endpoint, **redirect_kwargs)), form
    return None, form


# ---- Реєстр ----------------------------------------------------------------

@admin_bp.route('/quizzes')
@permission_required('quizzes.view')
def quizzes_list():
    """Реєстр тестів: де вони є, чи готові, чи вистачає даних БПР."""
    filters = {'q': _listing.text_arg('q')}

    # selectinload на instances: нижче ми обходимо `course.instances`, щоб
    # знайти перевизначення тесту, і без цього кожен курс у реєстрі тягнув
    # окремий запит за своїми проведеннями.
    courses = _listing.apply_search(
        Course.query, filters['q'], [Course.title, Course.slug],
    ).options(selectinload(Course.instances)).order_by(Course.title).all()

    # Теж selectinload, а не joinedload: questions -- колекція, і join
    # розмножував би рядок тесту на кожне питання (13 тестів по 30 питань дають
    # 390 рядків замість двох запитів).
    quizzes = CourseQuiz.query.options(selectinload(CourseQuiz.questions)).all()
    by_course = {q.course_id: q for q in quizzes if q.course_id}
    by_instance = {q.instance_id: q for q in quizzes if q.instance_id}

    rows = []
    for course in courses:
        quiz = by_course.get(course.id)
        overrides = [
            {'instance': inst, 'quiz': by_instance[inst.id]}
            for inst in course.instances if inst.id in by_instance
        ]
        rows.append({
            'course': course,
            'quiz': quiz,
            'overrides': overrides,
            # Без цих даних тест не відкриється, тож показуємо причину поруч.
            'bpr_missing': not (course.bpr_event_number or '').strip()
                           or not course.cpd_points,
        })

    return render_template(
        'admin/quizzes.html',
        rows=rows,
        filters=filters,
        filter_args=_listing.filter_args(filters),
        total_active=sum(1 for q in quizzes if q.is_active),
    )


# ---- Редактор: тест курсу --------------------------------------------------

@admin_bp.route('/courses/<int:course_id>/quiz', methods=['GET', 'POST'])
@permission_required('quizzes.manage')
def course_quiz_edit(course_id):
    course = db.session.get(Course, course_id)
    if course is None:
        flash('Курс не знайдено', 'error')
        return redirect(url_for('admin.courses_list'))

    quiz = _quiz_for(course=course)
    if request.method == 'POST':
        response, form = _save_editor(
            quiz, 'admin.course_quiz_edit', course_id=course.id)
        if response is not None:
            return response
    else:
        form = CourseQuizForm(obj=quiz)
    return _render_editor(quiz, course, None, form)


# ---- Редактор: перевизначення на проведенні --------------------------------

@admin_bp.route('/instances/<int:instance_id>/quiz', methods=['GET', 'POST'])
@permission_required('quizzes.manage')
def instance_quiz_edit(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if instance is None:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    quiz = _quiz_for(instance=instance)
    if request.method == 'POST':
        response, form = _save_editor(
            quiz, 'admin.instance_quiz_edit', instance_id=instance.id)
        if response is not None:
            return response
    else:
        form = CourseQuizForm(obj=quiz)
    return _render_editor(quiz, instance.course, instance, form)


@admin_bp.route('/quizzes/<int:quiz_id>/delete', methods=['POST'])
@permission_required('quizzes.delete')
def quiz_delete(quiz_id):
    quiz = db.session.get(CourseQuiz, quiz_id)
    if quiz is None:
        flash('Тест не знайдено', 'error')
        return redirect(url_for('admin.quizzes_list'))

    course_id, instance_id = quiz.course_id, quiz.instance_id
    db.session.delete(quiz)
    if try_commit(log_context=f'quiz_delete id={quiz_id}'):
        audit_logger.info('Admin %s deleted quiz %s', current_user.email, quiz_id)
        flash('Тест видалено. Результати учасників збережено.', 'success')
    if instance_id:
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))
    return redirect(url_for('admin.course_edit', course_id=course_id))


# Стан тестування у фільтрі -- РІВНО ці три значення, і жодного більше.
# attempts_exhausted / in_progress / profile_incomplete народжуються в
# quiz_service.eligibility_map УЖЕ ПІСЛЯ вибірки сторінки (їм потрібен
# контекст конкретних реєстрацій), тож фільтр по них звузив би лише поточну
# сторінку, а пейджер і далі показував би повний total -- та сама пастка,
# про яку попереджає коментар нижче про total_count/passed_count/issued_count.
# Тут -- лише те, що виражається прямим SQL-виразом на EventRegistration.
_QUIZ_STATE_CHOICES = {
    'passed': 'Склали',
    'not_passed': 'Не склали',
    'no_certificate': 'Без сертифіката',
}
_QUIZ_PAYMENT_CHOICES = {'paid': 'Оплачено', 'unpaid': 'Не оплачено'}


def _quiz_results_filters():
    """Фільтри реєстру результатів -- спільні для списку й для `_back()`."""
    return {
        'q': _listing.text_arg('q'),
        'state': _listing.choice_arg('state', _QUIZ_STATE_CHOICES),
        'payment': _listing.choice_arg('payment', _QUIZ_PAYMENT_CHOICES),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _back_to_quiz_results(instance_id):
    """Безпечний редірект назад до результатів групи зі збереженим зрізом.

    Спільний `_listing.back_redirect` перечитує й перевіряє кожен параметр
    зрізу тим самим способом, що й роут списку (НЕ request.referrer -- той
    керований клієнтом і відкриває open redirect). `instance_id` не з
    query string -- він завжди відомий із самої реєстрації (reg.instance_id),
    тож звірки не потребує. Джерело фільтрів -- query string запиту дії
    (unlock/reset): рядкові форми несуть зріз у action-URL через `back_args`.
    """
    return _listing.back_redirect(
        'admin.instance_quiz_results', _quiz_results_filters(),
        {'instance_id': instance_id},
    )


# ---- Результати по групі ---------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/quiz-results')
@permission_required('quizzes.view')
def instance_quiz_results(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if instance is None:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    base = (
        EventRegistration.query
        .filter_by(instance_id=instance.id)
        .filter(EventRegistration.status != 'cancelled')
    )

    filters = _quiz_results_filters()

    # Сортування перенесене в SQL (було `rows.sort` у Python): при пагінації
    # сортування всередині сторінки впорядковувало б лише її, і «ще не склали»
    # опинялися б на кожній сторінці окремою купкою.
    query = (
        base
        .join(User, EventRegistration.user_id == User.id)
        .options(
            # medical_profile -- бо `eligibility` питає повноту анкети, і без
            # цього кожен рядок групи тягнув би окремий запит (учасники різні,
            # тож identity-map не рятує, як у кабінеті одного користувача).
            contains_eager(EventRegistration.user).joinedload(User.medical_profile),
            joinedload(EventRegistration.quiz_attempts),
            joinedload(EventRegistration.certificate),
        )
    )
    query = _listing.apply_search(query, filters['q'], [
        User.first_name, User.last_name, User.email,
    ])
    if filters['state'] == 'passed':
        query = query.filter(EventRegistration.quiz_passed_at.isnot(None))
    elif filters['state'] == 'not_passed':
        query = query.filter(EventRegistration.quiz_passed_at.is_(None))
    elif filters['state'] == 'no_certificate':
        query = query.filter(~EventRegistration.certificate.has())
    if filters['payment'] == 'paid':
        query = query.filter(EventRegistration.payment_status == 'paid')
    elif filters['payment'] == 'unpaid':
        query = query.filter(EventRegistration.payment_status != 'paid')
    query = query.order_by(EventRegistration.quiz_passed_at.is_(None), User.last_name)

    page = _listing.page_arg()
    per_page = _listing.per_page_arg()
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    registrations = pagination.items

    # Контекст будуємо один раз: `eligibility_map` і `resolve_quiz` без нього
    # вибирали ті самі два рядки `course_quizzes` удруге.
    #
    # На порожній сторінці контекст НЕ передаємо в `resolve_quiz`: він
    # побудований із нуля реєстрацій, тож у ньому немає ні перевизначення, ні
    # тесту курсу, і заголовок сторінки збрехав би «тест не налаштований» там,
    # де тест є.
    context = quiz_service.build_batch_context(registrations) if registrations else None
    quiz = quiz_service.resolve_quiz(instance, context)
    states = quiz_service.eligibility_map(registrations, context=context)
    rows = []
    for reg in registrations:
        finished = [a for a in reg.quiz_attempts if a.is_finished]
        rows.append({
            'reg': reg,
            'state': states[reg.id],
            'attempts': finished,
            'best': max((a.score or 0 for a in finished), default=None),
        })

    # Лічильники -- по ВСІЙ групі (`base`), а не по зрізу й не по сторінці:
    # це показник готовності заходу до видачі сертифікатів, і «12 із 40» під
    # фільтром чи на другій сторінці мусить означати те саме, що без нього.
    # Раніше total_count брався з `pagination.total`, що збігалося з розміром
    # групи лише тому, що фільтрів на цій сторінці не було; тепер вони є, тож
    # рахуємо його з `base` окремо, як і решту двох.
    from app.models.certificate import Certificate
    total_count = base.count()
    passed_count = base.filter(
        EventRegistration.quiz_passed_at.isnot(None)).count()
    issued_count = base.join(
        Certificate, Certificate.registration_id == EventRegistration.id).count()

    filter_args = _listing.filter_args(filters)
    return render_template(
        'admin/quiz_results.html',
        instance=instance,
        quiz=quiz,
        rows=rows,
        pagination=pagination,
        total_count=total_count,
        passed_count=passed_count,
        issued_count=issued_count,
        filters=filters,
        filter_args=filter_args,
        back_args=_listing.back_args(filter_args, pagination.page),
        state_options=list(_QUIZ_STATE_CHOICES.items()),
        payment_options=list(_QUIZ_PAYMENT_CHOICES.items()),
        per_page_options=_listing.PER_PAGE_OPTIONS,
    )


# ---- Детальний розбір по учаснику ------------------------------------------

@admin_bp.route('/registrations/<int:reg_id>/quiz')
@permission_required('quizzes.view')
def registration_quiz_detail(reg_id):
    """Чому тест складено або ні: кожна спроба, кожне питання, кожна відповідь.

    Відповідає на питання «у людини багато помилок -- у чому саме»: поруч
    стоять обрана й правильна відповідь. Тут це припустимо, бо сторінка
    адмінська; учаснику правильні відповіді не показуються ніде.
    """
    reg = db.session.query(EventRegistration).options(
        joinedload(EventRegistration.user).joinedload(User.medical_profile),
        joinedload(EventRegistration.quiz_attempts),
        joinedload(EventRegistration.certificate),
        joinedload(EventRegistration.instance),
    ).filter_by(id=reg_id).first()
    if reg is None:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    # Найсвіжіша спроба -- перша: саме її зазвичай і прийшли дивитися.
    attempts = sorted(reg.quiz_attempts, key=lambda a: a.attempt_number,
                      reverse=True)
    reports = [
        {'attempt': attempt, 'rows': quiz_service.attempt_report(attempt)}
        for attempt in attempts
    ]

    state = quiz_service.eligibility(reg)
    return render_template(
        'admin/registration_quiz.html',
        reg=reg,
        instance=reg.instance,
        quiz=state.quiz,
        state=state,
        statuses=quiz_service,
        reports=reports,
        attempts_left=quiz_service.attempts_left(reg, state.quiz),
        profile=reg.user.medical_profile if reg.user else None,
    )


# ---- Спроби окремого учасника ----------------------------------------------

@admin_bp.route('/registrations/<int:reg_id>/quiz/unlock', methods=['POST'])
@permission_required('quizzes.manage')
def registration_quiz_unlock(reg_id):
    """Видати додаткові спроби (технічний збій, спірний випадок).

    Числом, а не прапорцем «розблоковано»: інакше неможливо було б дати рівно
    одну спробу.
    """
    reg = db.session.get(EventRegistration, reg_id)
    if reg is None:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    extra = request.form.get('extra', type=int)
    if extra is None or not 1 <= extra <= 10:
        flash('Вкажіть від 1 до 10 додаткових спроб', 'error')
        return _back_to_quiz_results(reg.instance_id)

    reg.quiz_extra_attempts = (reg.quiz_extra_attempts or 0) + extra
    if try_commit(log_context=f'quiz_unlock reg={reg_id}'):
        audit_logger.info(
            'Admin %s granted %d extra quiz attempts to reg %s (total extra %d)',
            current_user.email, extra, reg_id, reg.quiz_extra_attempts,
        )
        flash(f'Додано спроб: {extra}.', 'success')
    return _back_to_quiz_results(reg.instance_id)


@admin_bp.route('/registrations/<int:reg_id>/quiz/reset', methods=['POST'])
@permission_required('quizzes.manage')
def registration_quiz_reset(reg_id):
    """Обнулити результат тестування.

    Сертифікат при цьому НЕ відкликається -- це окрема дія з окремим слідом в
    адмінці. Інакше одна кнопка тихо робила б дві різні речі.
    """
    reg = db.session.get(EventRegistration, reg_id)
    if reg is None:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    removed = QuizAttempt.query.filter_by(registration_id=reg.id).delete()
    reg.quiz_passed_at = None
    reg.quiz_extra_attempts = 0
    if try_commit(log_context=f'quiz_reset reg={reg_id}'):
        audit_logger.info(
            'Admin %s reset quiz for reg %s (%d attempts removed)',
            current_user.email, reg_id, removed,
        )
        note = ('. Сертифікат лишився виданим – відкликайте окремо, якщо треба'
                if reg.certificate is not None else '')
        flash(f'Тестування обнулено, спроб видалено: {removed}{note}.', 'success')
    return _back_to_quiz_results(reg.instance_id)
