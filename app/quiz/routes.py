"""Проходження тесту учасником: умови -> питання -> звірка -> результат.

Одне питання на екран, відповіді пишуться на сервер одразу. Спроб лише три, тож
закрита вкладка, розряджений телефон чи втрачений зв'язок не мусять з'їдати
жодної: незавершена спроба продовжується з того ж місця.

Завершити можна лише коли відповіді є на всі питання. Це навмисна незручність:
випадковий клік «Завершити» на половині тесту коштував би спроби, а
непозначені питання все одно рахуються неправильними.

Правильні відповіді у шаблони не потрапляють НІКОЛИ -- усе, що бачить браузер,
збирає `quiz_service.attempt_view_model`.
"""
import logging

from flask import (
    abort, flash, redirect, render_template, request, url_for,
)
from flask_babel import gettext as _
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.models.quiz_attempt import QuizAttempt
from app.models.registration import EventRegistration
from app.quiz import quiz_bp
from app.services import quiz_service

logger = logging.getLogger(__name__)


def _own_registration(reg_id):
    """Реєстрація поточного користувача або 404.

    Чужа реєстрація і неіснуюча дають однаковий результат -- інакше по коду
    відповіді можна було б перебрати, які id існують.
    """
    reg = db.session.get(EventRegistration, reg_id)
    if reg is None or reg.user_id != current_user.id:
        abort(404)
    return reg


def _own_attempt(attempt_id):
    attempt = db.session.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.user_id != current_user.id:
        abort(404)
    return attempt


def _first_unanswered(attempt):
    """Позиція першого питання без відповіді (або 0, якщо всі є)."""
    for position, question_id in enumerate(attempt.question_ids or []):
        if attempt.chosen_position(question_id) is None:
            return position
    return 0


def _unanswered_numbers(attempt):
    return [
        position + 1
        for position, question_id in enumerate(attempt.question_ids or [])
        if attempt.chosen_position(question_id) is None
    ]


@quiz_bp.route('/<int:reg_id>')
@login_required
def start(reg_id):
    """Умови тесту: скільки питань, поріг, скільки спроб лишилось."""
    reg = _own_registration(reg_id)
    state = quiz_service.eligibility(reg)

    if state.status == quiz_service.PASSED:
        return redirect(url_for('quiz.done', reg_id=reg.id))

    return render_template(
        'quiz/start.html',
        registration=reg,
        instance=reg.instance,
        state=state,
        quiz=state.quiz,
        statuses=quiz_service,
    )


@quiz_bp.route('/<int:reg_id>/start', methods=['POST'])
@login_required
@limiter.limit('30 per hour')
def begin(reg_id):
    reg = _own_registration(reg_id)
    state = quiz_service.eligibility(reg)
    if not state.is_actionable:
        flash(_('Тестування зараз недоступне.'), 'error')
        return redirect(url_for('quiz.start', reg_id=reg.id))

    attempt = quiz_service.start_attempt(reg)
    db.session.commit()
    return redirect(url_for('quiz.question', attempt_id=attempt.id))


@quiz_bp.route('/attempt/<int:attempt_id>')
@login_required
def question(attempt_id):
    attempt = _own_attempt(attempt_id)
    if attempt.is_finished:
        return redirect(url_for('quiz.result', attempt_id=attempt.id))

    requested = request.args.get('position', type=int)
    if requested is None:
        # Відповіді є на все -- людині лишилось завершити, а не гортати з
        # першого питання. Так, зокрема, поводиться повернення за старим
        # посиланням: інакше кнопку «Завершити» довелось би шукати кліками.
        if not _unanswered_numbers(attempt):
            return redirect(url_for('quiz.review', attempt_id=attempt.id))
        position = _first_unanswered(attempt)
    else:
        position = requested
    view = quiz_service.attempt_view_model(attempt, position)
    if view is None:
        # Позиція поза межами -- не 404: людина могла правити URL або
        # повернутися за старим посиланням.
        return redirect(url_for('quiz.question', attempt_id=attempt.id))

    return render_template(
        'quiz/question.html',
        attempt=attempt,
        view=view,
        answered=attempt.answered_count,
    )


@quiz_bp.route('/attempt/<int:attempt_id>/answer', methods=['POST'])
@login_required
def answer(attempt_id):
    """Зберегти відповідь і перейти далі.

    Порожній вибір не помилка: людина могла натиснути «Далі», щоб повернутися
    до питання пізніше. Тоді просто нічого не пишемо.
    """
    attempt = _own_attempt(attempt_id)
    if attempt.is_finished:
        return redirect(url_for('quiz.result', attempt_id=attempt.id))

    position = request.form.get('position', type=int) or 0
    question_id = request.form.get('question_id')
    choice = request.form.get('choice')

    if choice is not None and choice != '':
        if not quiz_service.record_answer(attempt, question_id, choice):
            logger.warning(
                'Rejected quiz answer: attempt=%s question=%r choice=%r',
                attempt.id, question_id, choice,
            )
        db.session.commit()

    total = len(attempt.question_ids or [])
    target = position + 1 if request.form.get('direction') != 'back' else position - 1
    if target >= total:
        return redirect(url_for('quiz.review', attempt_id=attempt.id))
    if target < 0:
        target = 0
    return redirect(url_for('quiz.question', attempt_id=attempt.id, position=target))


@quiz_bp.route('/attempt/<int:attempt_id>/review')
@login_required
def review(attempt_id):
    """Звірка перед завершенням: усі питання та обрані відповіді."""
    attempt = _own_attempt(attempt_id)
    if attempt.is_finished:
        return redirect(url_for('quiz.result', attempt_id=attempt.id))

    return render_template(
        'quiz/review.html',
        attempt=attempt,
        items=quiz_service.attempt_view_models(attempt),
        unanswered=_unanswered_numbers(attempt),
    )


@quiz_bp.route('/attempt/<int:attempt_id>/submit', methods=['POST'])
@login_required
@limiter.limit('30 per hour')
def submit(attempt_id):
    attempt = _own_attempt(attempt_id)
    if attempt.is_finished:
        return redirect(url_for('quiz.result', attempt_id=attempt.id))

    missing = _unanswered_numbers(attempt)
    if missing:
        # Не даємо витратити спробу випадковим кліком: непозначені питання
        # рахувалися б неправильними.
        flash(_('Спершу відповідьте на всі питання. Залишились: %(numbers)s',
                numbers=', '.join(str(n) for n in missing)), 'error')
        return redirect(url_for('quiz.review', attempt_id=attempt.id))

    quiz_service.submit_attempt(attempt)
    return redirect(url_for('quiz.result', attempt_id=attempt.id))


@quiz_bp.route('/attempt/<int:attempt_id>/result')
@login_required
def result(attempt_id):
    attempt = _own_attempt(attempt_id)
    if not attempt.is_finished:
        return redirect(url_for('quiz.question', attempt_id=attempt.id))

    reg = attempt.registration
    state = quiz_service.eligibility(reg)
    return render_template(
        'quiz/result.html',
        attempt=attempt,
        registration=reg,
        state=state,
        statuses=quiz_service,
        # Номери незарахованих питань -- без правильних відповідей. Рахує
        # сервіс: доки це була друга реалізація оцінювання, вона розійшлася б
        # із `grade_attempt` на першій же правці.
        wrong_numbers=quiz_service.wrong_numbers(attempt),
    )


@quiz_bp.route('/<int:reg_id>/done')
@login_required
def done(reg_id):
    """Сторінка привітання з посиланням на сертифікат."""
    reg = _own_registration(reg_id)
    if reg.quiz_passed_at is None:
        return redirect(url_for('quiz.start', reg_id=reg.id))

    certificate = reg.certificate
    if certificate is not None and certificate.revoked:
        certificate = None
    return render_template(
        'quiz/done.html',
        registration=reg,
        instance=reg.instance,
        certificate=certificate,
        # Про лист питаємо журнал, а не вгадуємо: ця сторінка відкривається
        # іншим запитом, ніж той, що видавав сертифікат.
        email_sent=(certificate is not None
                    and quiz_service.certificate_email_sent(reg)),
    )
