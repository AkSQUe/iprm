"""Адмінка тестування: реєстр тестів, білдер питань, результати, розблокування.

Тест живе на курсі (базовий набір) або на проведенні (перевизначення), тож
редактор один, а входів до нього два. Створюється лениво -- при першому
відкритті сторінки, щоб адмін не тиснув окрему кнопку «створити тест».

Банк питань не входить у WTForms-форму: 10+ питань по 4 варіанти -- це репітер
із динамічною кількістю полів. У цьому проєкті такі речі робляться плоскими
іменами `question_N_*` і парсяться сервісом -- так само, як «блоки програми»
курсу (єдиний інший репітер тут).
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import _listing, admin_bp
from app.admin._helpers import try_commit
from app.admin.decorators import admin_required
from app.admin.forms import CourseQuizForm
from app.admin.routes_translations import apply_inline_translations
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_quiz import CourseQuiz
from app.models.quiz_attempt import QuizAttempt
from app.models.registration import EventRegistration
from app.services import quiz_service

audit_logger = logging.getLogger('audit')


def _quiz_for(course=None, instance=None, create=False):
    """Знайти (або створити) тест для курсу чи проведення."""
    if instance is not None:
        quiz = CourseQuiz.query.filter_by(instance_id=instance.id).first()
    else:
        quiz = CourseQuiz.query.filter_by(course_id=course.id).first()
    if quiz is None and create:
        quiz = CourseQuiz(
            course_id=course.id if instance is None else None,
            instance_id=instance.id if instance is not None else None,
        )
        db.session.add(quiz)
        db.session.flush()
    return quiz


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

    questions = quiz_service.extract_questions_from_form(request.form)
    quiz_service.save_questions_for_quiz(quiz, questions)
    db.session.flush()
    _apply_question_translations(quiz)

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
@admin_required
def quizzes_list():
    """Реєстр тестів: де вони є, чи готові, чи вистачає даних БПР."""
    filters = {'q': _listing.text_arg('q')}

    courses = _listing.apply_search(
        Course.query, filters['q'], [Course.title, Course.slug],
    ).order_by(Course.title).all()

    quizzes = CourseQuiz.query.options(joinedload(CourseQuiz.questions)).all()
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
        total_active=sum(1 for q in quizzes if q.is_active),
    )


# ---- Редактор: тест курсу --------------------------------------------------

@admin_bp.route('/courses/<int:course_id>/quiz', methods=['GET', 'POST'])
@admin_required
def course_quiz_edit(course_id):
    course = db.session.get(Course, course_id)
    if course is None:
        flash('Курс не знайдено', 'error')
        return redirect(url_for('admin.courses_list'))

    quiz = _quiz_for(course=course, create=True)
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
@admin_required
def instance_quiz_edit(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if instance is None:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    quiz = _quiz_for(instance=instance, create=True)
    if request.method == 'POST':
        response, form = _save_editor(
            quiz, 'admin.instance_quiz_edit', instance_id=instance.id)
        if response is not None:
            return response
    else:
        form = CourseQuizForm(obj=quiz)
    return _render_editor(quiz, instance.course, instance, form)


@admin_bp.route('/quizzes/<int:quiz_id>/delete', methods=['POST'])
@admin_required
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


# ---- Результати по групі ---------------------------------------------------

@admin_bp.route('/instances/<int:instance_id>/quiz-results')
@admin_required
def instance_quiz_results(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if instance is None:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    registrations = (
        EventRegistration.query
        .filter_by(instance_id=instance.id)
        .filter(EventRegistration.status != 'cancelled')
        .options(
            joinedload(EventRegistration.user),
            joinedload(EventRegistration.quiz_attempts),
            joinedload(EventRegistration.certificate),
        )
        .all()
    )

    quiz = quiz_service.resolve_quiz(instance)
    rows = []
    for reg in registrations:
        finished = [a for a in reg.quiz_attempts if a.is_finished]
        rows.append({
            'reg': reg,
            'state': quiz_service.eligibility(reg),
            'attempts': finished,
            'best': max((a.score or 0 for a in finished), default=None),
        })
    rows.sort(key=lambda r: (r['reg'].quiz_passed_at is None,
                             r['reg'].user.last_name or ''))

    return render_template(
        'admin/quiz_results.html',
        instance=instance,
        quiz=quiz,
        rows=rows,
        passed_count=sum(1 for r in rows if r['reg'].quiz_passed_at),
    )


# ---- Спроби окремого учасника ----------------------------------------------

@admin_bp.route('/registrations/<int:reg_id>/quiz/unlock', methods=['POST'])
@admin_required
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
        return redirect(url_for('admin.instance_quiz_results',
                                instance_id=reg.instance_id))

    reg.quiz_extra_attempts = (reg.quiz_extra_attempts or 0) + extra
    if try_commit(log_context=f'quiz_unlock reg={reg_id}'):
        audit_logger.info(
            'Admin %s granted %d extra quiz attempts to reg %s (total extra %d)',
            current_user.email, extra, reg_id, reg.quiz_extra_attempts,
        )
        flash(f'Додано спроб: {extra}.', 'success')
    return redirect(url_for('admin.instance_quiz_results',
                            instance_id=reg.instance_id))


@admin_bp.route('/registrations/<int:reg_id>/quiz/reset', methods=['POST'])
@admin_required
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
        note = ('. Сертифікат лишився виданим -- відкликайте окремо, якщо треба'
                if reg.certificate is not None else '')
        flash(f'Тестування обнулено, спроб видалено: {removed}{note}.', 'success')
    return redirect(url_for('admin.instance_quiz_results',
                            instance_id=reg.instance_id))
