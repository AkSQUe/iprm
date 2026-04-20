import logging

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user
from sqlalchemy.orm import joinedload

from app.extensions import db, limiter
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.registration import registration_bp
from app.registration.forms import EventRegistrationForm
from app.services import registration_service
from app.services.partner_auth import (
    PrefillTokenError,
    decode_prefill_token,
    get_or_create_partner_user,
)

logger = logging.getLogger(__name__)


class EventAdapter:
    """Сумісне представлення CourseInstance для шаблонів register/confirmation.

    Шаблони історично оперують сутністю `event` із полями `title`, `price`,
    `start_date` тощо. Адаптер проксує їх із CourseInstance+Course, не
    засмічуючи модель сумісними властивостями.
    """

    def __init__(self, instance):
        self._inst = instance
        course = instance.course
        self.id = instance.id
        self.slug = course.slug if course else None
        self.title = course.title if course else ''
        self.subtitle = course.subtitle if course else None
        self.description = course.description if course else None
        self.short_description = course.short_description if course else None
        self.start_date = instance.start_date
        self.end_date = instance.end_date
        self.event_format = instance.event_format
        self.format_label = instance.format_label
        self.location = instance.location
        self.online_link = instance.online_link
        self.price = instance.effective_price
        self.cpd_points = instance.effective_cpd_points
        self.max_participants = instance.effective_max_participants
        self.trainer = instance.effective_trainer
        self.card_image = course.card_image if course else None
        self.hero_image = course.hero_image if course else None
        self.tags = course.tags if course else []
        self.target_audience = course.target_audience if course else []
        self.faq = course.faq if course else []


def _maybe_consume_prefill_token():
    """If ?prefill=<jwt> is present, auto-login / create user and return payload.

    Returns dict with prefill fields for form rendering, or None.
    On invalid token: logs warning and silently drops prefill (user sees login page).
    """
    token = request.args.get('prefill')
    if not token:
        return None
    try:
        payload = decode_prefill_token(token)
    except PrefillTokenError as exc:
        logger.warning('Prefill token rejected: %s', exc)
        return None

    user = get_or_create_partner_user(payload)
    if not current_user.is_authenticated or current_user.id != user.id:
        login_user(user)
    return {
        'phone': payload.phone or '',
        'first_name': payload.first_name or '',
        'last_name': payload.last_name or '',
    }


def _login_next_path():
    """Будує `next`-URL для редіректу на /login, прибираючи `prefill`-токен.

    Prefill-токени одноразові: передавати їх через login flow нема сенсу
    (і небезпечно, бо токен залишиться в session-history).
    """
    args = request.args.to_dict(flat=True)
    args.pop('prefill', None)
    return url_for(request.endpoint, **request.view_args, **args)


@registration_bp.route('/<int:event_id>/register')
def register_legacy(event_id):
    """Legacy URL: /registration/<event_id>/register -> redirect на catalog.

    Збережено для зворотної сумісності з email-розсилками партнерів та
    пошуковими системами. Переходить на каталог, де користувач обере
    курс та конкретне проведення заново.
    """
    return redirect(url_for('courses.course_list'), code=301)


@registration_bp.route('/instance/<int:instance_id>/register', methods=['GET', 'POST'])
@limiter.limit("10 per hour", methods=['POST'])
def register_instance(instance_id):
    """Нова модель: реєстрація на конкретне проведення курсу (CourseInstance)."""
    prefill = _maybe_consume_prefill_token() if request.method == 'GET' else None

    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=_login_next_path()))

    if not current_user.email_confirmed:
        flash('Для реєстрації на курс необхідно підтвердити email', 'warning')
        return redirect(url_for('auth.account'))

    instance = db.session.query(CourseInstance).options(
        joinedload(CourseInstance.course),
        joinedload(CourseInstance.trainer),
    ).filter_by(id=instance_id).first()
    if not instance or not instance.course or not instance.course.is_active:
        abort(404)

    existing = registration_service.find_existing(current_user.id, instance.id)

    if existing and existing.status != 'cancelled':
        flash('Ви вже зареєстровані на цей курс', 'info')
        return redirect(url_for('registration.confirmation', registration_id=existing.id))

    if not instance.is_registration_open:
        flash('Реєстрацію на цей курс закрито', 'error')
        return redirect(url_for('courses.course_by_slug', slug=instance.course.slug))

    form = EventRegistrationForm(data=prefill) if prefill else EventRegistrationForm()

    if form.validate_on_submit():
        has_capacity, _ = registration_service.check_capacity(instance_id)
        if not has_capacity:
            db.session.rollback()
            flash('На жаль, місць більше немає', 'error')
            return redirect(url_for('courses.course_by_slug', slug=instance.course.slug))

        try:
            form_data = {
                'phone': form.phone.data.strip(),
                'specialty': form.specialty.data.strip(),
                'workplace': form.workplace.data.strip(),
                'experience_years': form.experience_years.data,
                'license_number': form.license_number.data,
            }
            reg, is_free = registration_service.create_or_reactivate(
                current_user.id, instance, form_data, existing,
            )
            db.session.commit()
            if is_free:
                flash('Реєстрацію підтверджено', 'success')
            else:
                flash('Реєстрацію створено. Очікує оплати.', 'info')
            return redirect(url_for('registration.confirmation', registration_id=reg.id))
        except Exception:
            logger.exception('Failed to register user %d for instance %d', current_user.id, instance_id)
            db.session.rollback()
            flash('Помилка при реєстрації. Спробуйте ще раз.', 'error')

    return render_template(
        'registration/register.html',
        form=form,
        event=EventAdapter(instance),
    )


@registration_bp.route('/<int:registration_id>')
@login_required
def confirmation(registration_id):
    reg = db.session.query(EventRegistration).options(
        joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
    ).filter_by(id=registration_id).first()
    if not reg or reg.user_id != current_user.id:
        abort(404)

    liqpay_data = None
    liqpay_signature = None
    liqpay_checkout_url = None

    needs_payment = (
        reg.status == 'pending'
        and reg.payment_status == 'unpaid'
        and reg.payment_amount
        and reg.payment_amount > 0
    )
    if needs_payment:
        from app.services.liqpay import get_liqpay_service
        service = get_liqpay_service()
        if service.is_configured:
            order_id = f'REG-{reg.id}'
            result_url = url_for('payments.success', order_id=order_id, _external=True)
            server_url = url_for('payments.liqpay_callback', _external=True)
            description = (
                reg.instance.course.title if reg.instance and reg.instance.course
                else reg.target_title or f'Реєстрація #{reg.id}'
            )
            liqpay_data, liqpay_signature, liqpay_checkout_url = (
                service.create_payment_form(
                    order_id=order_id,
                    amount=float(reg.payment_amount),
                    description=description,
                    result_url=result_url,
                    server_url=server_url,
                )
            )

    template_event = EventAdapter(reg.instance) if reg.instance else None

    return render_template(
        'registration/confirmation.html',
        reg=reg,
        event=template_event,
        liqpay_data=liqpay_data,
        liqpay_signature=liqpay_signature,
        liqpay_checkout_url=liqpay_checkout_url,
    )
