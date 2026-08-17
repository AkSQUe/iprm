"""Публічний каталог онлайн-курсів.

Окремий розділ від /courses: там офлайн-заходи з датами, містами й місцями,
тут -- навчання, що йде в Sintegrum і не має ані дати, ані обмеження місць.

Читаємо ТІЛЬКИ дзеркало в нашій базі. Жодного звернення до Sintegrum на
рендері: недоступність чужого API не повинна робити розділ порожнім.

access_url у публічні шаблони не передається ніколи -- це фактично ключ від
навчання. Учасник отримує його лише через наш токен-редірект після оплати.
"""
import logging

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.online import online_bp

logger = logging.getLogger(__name__)


def _published_query():
    return OnlineCourse.query.filter(
        OnlineCourse.is_published.is_(True),
        OnlineCourse.is_vanished.is_(False),
    )


@online_bp.route('/')
def course_list():
    courses = _published_query().order_by(
        OnlineCourse.is_featured.desc(),
        OnlineCourse.sort_order,
        OnlineCourse.remote_name,
    ).all()

    return render_template(
        'online/list.html',
        active_nav='online',
        courses=courses,
    )


@online_bp.route('/<slug>')
def course_detail(slug):
    course = _published_query().filter_by(slug=slug).first()
    if not course:
        # Неопублікований або зниклий курс не існує для публіки -- саме 404,
        # а не 403: інакше сторінка підтверджувала б, що такий курс у нас є.
        abort(404)

    related = [
        item for item in _published_query().order_by(
            OnlineCourse.is_featured.desc(), OnlineCourse.sort_order,
        ).limit(4).all()
        if item.id != course.id
    ][:3]

    existing = None
    if current_user.is_authenticated:
        existing = _live_enrollment(current_user.id, course.id)

    return render_template(
        'online/detail.html',
        active_nav='online',
        course=course,
        related=related,
        checkout_available=course.is_purchasable,
        existing_enrollment=existing,
    )


def _live_enrollment(user_id, course_id):
    """Нескасоване замовлення цього користувача на цей курс."""
    return OnlineEnrollment.query.filter(
        OnlineEnrollment.user_id == user_id,
        OnlineEnrollment.online_course_id == course_id,
        OnlineEnrollment.status != 'cancelled',
    ).first()


@online_bp.route('/<slug>/checkout', methods=['GET', 'POST'])
@login_required
@limiter.limit('20 per hour')
def checkout(slug):
    """Оформлення покупки: створює замовлення і віддає форму LiqPay.

    Логін обов'язковий (рішення Q5): доступ персональний, і його треба
    десь показувати повторно -- у кабінеті.
    """
    course = _published_query().filter_by(slug=slug).first()
    if not course:
        abort(404)

    if not course.is_purchasable:
        flash(_('Цей курс поки не можна купити'), 'error')
        return redirect(url_for('online.course_detail', slug=course.slug))

    enrollment = _live_enrollment(current_user.id, course.id)

    if enrollment and enrollment.is_paid:
        flash(_('Ви вже придбали цей курс'), 'info')
        return redirect(url_for('auth.account'))

    if enrollment is None:
        # Сума фіксується тут і надалі не перераховується: зміна ціни на
        # сайті не має чіпати вже оформлене замовлення.
        enrollment = OnlineEnrollment(
            user_id=current_user.id,
            online_course_id=course.id,
            payment_amount=course.effective_price,
            payment_status='unpaid',
            status='pending',
        )
        db.session.add(enrollment)
        try:
            db.session.commit()
        except Exception:
            # Найімовірніше -- гонка двох вкладок і частковий унікальний
            # індекс. Тоді замовлення вже існує, ним і користуємось.
            db.session.rollback()
            logger.exception('Failed to create enrollment for course %s', course.id)
            enrollment = _live_enrollment(current_user.id, course.id)
            if enrollment is None:
                flash(_('Не вдалося оформити замовлення. Спробуйте ще раз.'), 'error')
                return redirect(url_for('online.course_detail', slug=course.slug))

    promo_error = None
    if request.method == 'POST':
        promo_error = _handle_promo(enrollment, course)

    return render_template(
        'online/checkout.html',
        active_nav='online',
        course=course,
        enrollment=enrollment,
        promo_error=promo_error,
        **_liqpay_context(enrollment, course),
    )


def _handle_promo(enrollment, course):
    """Застосувати або зняти промокод. Повертає текст помилки або None.

    Сума перераховується від ЦІНИ КУРСУ, а не від поточної
    `payment_amount`: інакше друге застосування коду рахувало б знижку від
    уже здешевленої суми, і кожне натискання робило б курс дешевшим.
    """
    from app.services import promo_service
    from app.services.promo_service import PromoError

    if enrollment.is_paid:
        return None

    if request.form.get('remove_promo'):
        promo_service.detach_from_enrollment(enrollment)
        enrollment.payment_amount = course.effective_price
        db.session.commit()
        flash(_('Промокод знято'), 'info')
        return None

    raw = (request.form.get('promo_code') or '').strip()
    if not raw:
        return None

    try:
        promo, _discount, _final = promo_service.validate_for_online(
            raw, amount=course.effective_price, user_id=current_user.id,
        )
        promo_service.assert_user_limit(
            promo, current_user.id, ignore_enrollment_id=enrollment.id,
        )
        promo_service.apply_to_enrollment(
            promo, enrollment, course.effective_price,
        )
        db.session.commit()
    except PromoError as exc:
        db.session.rollback()
        return str(exc)
    except Exception:
        db.session.rollback()
        logger.exception('Failed to apply promo to %s', enrollment.order_id)
        return str(_('Не вдалося застосувати промокод. Спробуйте ще раз.'))

    flash(_('Промокод застосовано'), 'success')
    return None


def _liqpay_context(enrollment, course):
    """Дані форми LiqPay. Порожньо, якщо платіжку не налаштовано."""
    from app.services.liqpay import get_liqpay_service

    service = get_liqpay_service()
    if not service.is_configured or not enrollment.payment_amount:
        return {'liqpay_data': None, 'liqpay_signature': None,
                'liqpay_checkout_url': None}

    order_id = enrollment.order_id
    data, signature, checkout_url = service.create_payment_form(
        order_id=order_id,
        amount=float(enrollment.payment_amount),
        description=course.effective_title,
        result_url=url_for('payments.success', order_id=order_id, _external=True),
        server_url=url_for('payments.liqpay_callback', _external=True),
    )
    return {'liqpay_data': data, 'liqpay_signature': signature,
            'liqpay_checkout_url': checkout_url}


@online_bp.route('/access/<token>', localize=False)
@limiter.limit('30 per hour')
def access(token):
    """Тимчасове посилання на навчання.

    localize=False: посилання живе в листі, і мовний префікс тут лише
    множив би варіанти того самого токена.

    Ціль редіректу (спільне посилання реєстрації Sintegrum) не показується
    ні на сторінці помилки, ні в логах -- нею користуються лише через 302.
    """
    enrollment = OnlineEnrollment.query.filter_by(access_token=token).first()

    if enrollment is None:
        return render_template(
            'online/access_error.html', reason='unknown', enrollment=None,
        ), 404

    if not enrollment.is_paid:
        # Токен існує, але оплату скасовано або повернуто.
        return render_template(
            'online/access_error.html', reason='unpaid', enrollment=enrollment,
        ), 403

    if enrollment.access_is_expired:
        return render_template(
            'online/access_error.html', reason='expired', enrollment=enrollment,
        ), 410

    from app.services import sintegrum_access

    # Ціль -- готове посилання курсу або навчальний портал компанії: при
    # автоматичній видачі персонального посилання не існує, учасник заходить
    # під собою й бачить відкритий курс у своєму списку.
    target = sintegrum_access.target_url_for(enrollment)
    if not target:
        logger.error('Access target missing for %s', enrollment.order_id)
        return render_template(
            'online/access_error.html', reason='no_target', enrollment=enrollment,
        ), 503

    enrollment.access_last_opened_at = db.func.now()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to record access open for %s', enrollment.order_id)

    return redirect(target, code=302)


@online_bp.route('/access/<int:enrollment_id>/reissue', methods=['POST'])
@login_required
@limiter.limit('10 per hour')
def reissue_access(enrollment_id):
    """Перевипуск протермінованого посилання на вимогу учасника."""
    enrollment = db.session.get(OnlineEnrollment, enrollment_id)
    if enrollment is None or enrollment.user_id != current_user.id:
        abort(404)

    if not enrollment.is_paid:
        flash(_('Замовлення не оплачене'), 'error')
        return redirect(url_for('auth.account'))

    from app.services import sintegrum_access
    try:
        sintegrum_access.reissue(enrollment)
    except sintegrum_access.AccessProvisionError:
        flash(
            _('Не вдалося видати посилання. Ми вже розбираємось, '
              'напишіть нам, якщо це терміново.'),
            'error',
        )
        return redirect(url_for('auth.account'))

    flash(_('Нове посилання на навчання видано'), 'success')
    return redirect(url_for('online.access', token=enrollment.access_token))
