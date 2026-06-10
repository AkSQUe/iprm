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
from app.services.recaptcha import verify_request as verify_recaptcha
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
        self.card_image = course.card_src if course else None
        self.hero_image = course.hero_src if course else None
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


def _initial_form_data_from_user(user):
    """Pre-fill EventRegistrationForm з MedicalProfile (canonical) + User
    identity-полів (last_name/first_name). Phase 7: жодних fallback'ів
    на legacy-колонки User -- вони дропнуті.
    """
    profile = user.medical_profile
    return {
        'user_type': (profile.participant_type if profile else '') or '',
        'last_name': user.last_name or '',
        'first_name': user.first_name or '',
        'middle_name': (profile.middle_name if profile else '') or '',
        'phone': (profile.phone if profile else '') or '',
        'birth_date': profile.birth_date if profile else None,
        'education': (profile.education if profile else '') or '',
        'workplace': (profile.workplace if profile else '') or '',
        'position': (profile.position if profile else '') or '',
        'specializations': (profile.specializations if profile else []) or [],
    }


def _sync_medical_profile_from_form(user, form):
    """Записати медичні поля у MedicalProfile + identity-поля
    (last_name/first_name) у User. Створює MedicalProfile, якщо відсутній.
    Виставляє completed_at, коли профіль стає повним.
    """
    from datetime import datetime, timezone
    from app.models.medical_profile import MedicalProfile

    # User-level identity поля (last/first name -- частина identity, а
    # не медпрофілю).
    user.last_name = (form.last_name.data or '').strip() or None
    user.first_name = (form.first_name.data or '').strip() or None

    # Canonical: MedicalProfile.
    profile = user.medical_profile
    if profile is None:
        profile = MedicalProfile(user_id=user.id, source=MedicalProfile.SOURCE_SELF)
        db.session.add(profile)
        user.medical_profile = profile
    profile.participant_type = form.user_type.data
    profile.middle_name = (form.middle_name.data or '').strip() or None
    profile.phone = (form.phone.data or '').strip() or None
    profile.birth_date = form.birth_date.data
    profile.education = (form.education.data or '').strip() or None
    profile.workplace = (form.workplace.data or '').strip() or None
    profile.position = (form.position.data or '').strip() or None
    profile.specializations = list(form.specializations.data or [])

    if profile.is_complete and profile.completed_at is None:
        profile.completed_at = datetime.now(timezone.utc)


def _spec_labels(codes):
    """Локально імпортуємо щоб не тягнути specializations при cold-import
    routes.py під test-collection."""
    from app.models.specializations import labels_for_codes
    return labels_for_codes(codes)


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

    # Pre-fill: спершу беремо з User-профілю, потім партнерський токен (вища
    # пріоритетність -- зовнішня система знає актуальні дані краще, ніж
    # старий снапшот в User).
    initial = _initial_form_data_from_user(current_user)
    if prefill:
        initial.update({k: v for k, v in prefill.items() if v})
    form = EventRegistrationForm(data=initial)

    if form.validate_on_submit():
        if not verify_recaptcha(action='event_register'):
            flash('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.', 'error')
            return render_template(
                'registration/register.html',
                form=form, event=EventAdapter(instance),
                profile_complete=bool(
                    current_user.medical_profile
                    and current_user.medical_profile.is_complete
                ),
            )
        has_capacity, _ = registration_service.check_capacity(instance_id)
        if not has_capacity:
            db.session.rollback()
            flash('На жаль, місць більше немає', 'error')
            return redirect(url_for('courses.course_by_slug', slug=instance.course.slug))

        try:
            # 1) Phase 4: dual-write медичних полів у MedicalProfile
            #    (canonical) і User (shadow). Заповнює completed_at коли
            #    профіль стає повним (для майбутніх 2-click реєстрацій).
            _sync_medical_profile_from_form(current_user, form)

            # 2) Створити CourseRegistration. EventRegistration зберігає
            #    snapshot fields для історичної консистентності (snapshot
            #    показує що було під час події, навіть якщо профіль зміниться).
            specializations = form.specializations.data or []
            specialty_snapshot = ', '.join(
                _spec_labels(specializations)
            ) or (form.position.data or '').strip()
            form_data = {
                'phone': form.phone.data.strip(),
                'specialty': specialty_snapshot,
                'workplace': form.workplace.data.strip(),
                'experience_years': form.experience_years.data,
                'license_number': form.license_number.data,
            }
            reg, is_free = registration_service.create_or_reactivate(
                current_user.id, instance, form_data, existing,
            )
            db.session.commit()
            # Best-effort email-підтвердження. Збій SMTP не ламає реєстрацію.
            try:
                from app.services.email_service import EmailService
                EmailService.send_registration_confirmation(reg)
            except Exception:
                logger.exception(
                    'Failed to queue confirmation email for reg %d', reg.id,
                )
            if is_free:
                flash('Реєстрацію підтверджено', 'success')
            else:
                flash('Реєстрацію створено. Очікує оплати.', 'info')
            return redirect(url_for('registration.confirmation', registration_id=reg.id))
        except Exception:
            logger.exception('Failed to register user %d for instance %d', current_user.id, instance_id)
            db.session.rollback()
            flash('Помилка при реєстрації. Спробуйте ще раз.', 'error')

    profile_complete = bool(
        current_user.medical_profile
        and current_user.medical_profile.is_complete
    )
    return render_template(
        'registration/register.html',
        form=form,
        event=EventAdapter(instance),
        profile_complete=profile_complete,
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
