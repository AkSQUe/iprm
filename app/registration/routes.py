import io
import logging

from flask import (
    abort, flash, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user, login_required, login_user
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db, limiter
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from app.registration import registration_bp
from app.registration.forms import EventRegistrationForm, ParticipantCompletionForm
from app.services import participant_service, registration_service
from app.services.participant_service import ParticipantError
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
    """Pre-fill слім-форми реєстрації: ПІБ з User, телефон з MedicalProfile.

    Медична анкета (МОЗ №725) на формі реєстрації більше не збирається --
    вона заповнюється в особистому кабінеті (auth.certificate_data) як
    умова отримання сертифіката. Рішення 08.07.2026.
    """
    profile = user.medical_profile
    return {
        'last_name': user.last_name or '',
        'first_name': user.first_name or '',
        'phone': (profile.phone if profile else '') or '',
    }


def _sync_medical_profile_from_form(user, form):
    """Слім-синхронізація: identity-поля (ПІБ) у User + телефон у
    MedicalProfile (створюється за потреби). МОЗ-полями профілю володіє
    форма "Дані для сертифіката" в кабінеті -- тут їх не чіпаємо.
    """
    from app.models.medical_profile import MedicalProfile

    user.last_name = (form.last_name.data or '').strip() or None
    user.first_name = (form.first_name.data or '').strip() or None

    profile = user.medical_profile
    if profile is None:
        profile = MedicalProfile(user_id=user.id, source=MedicalProfile.SOURCE_SELF)
        db.session.add(profile)
        user.medical_profile = profile
    profile.phone = (form.phone.data or '').strip() or None


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

    # Підтвердження email НЕ блокує реєстрацію/оплату (Блок 4.1 фаза 2,
    # рішення Дмитра): лист підтвердження надсилається після списання
    # коштів (payment_ops.update_payment_status), а непідтверджені
    # оплачені реєстрації видно менеджеру для ручної звірки.

    instance = db.session.query(CourseInstance).options(
        joinedload(CourseInstance.course),
        joinedload(CourseInstance.trainer),
        selectinload(CourseInstance.tariffs),
    ).filter_by(id=instance_id).first()
    if not instance or not instance.course or not instance.course.is_active:
        abort(404)

    # Тарифна вилка: коли у проведення є активні тарифи, вибір обов'язковий.
    # GET ?tariff=<id> -- передвибір з пігулок на сторінці курсу.
    tariffs = instance.active_tariffs
    selected_tariff = None
    if tariffs:
        raw_id = (request.form.get('tariff_id') if request.method == 'POST'
                  else request.args.get('tariff'))
        try:
            wanted_id = int(raw_id) if raw_id else None
        except (TypeError, ValueError):
            wanted_id = None
        selected_tariff = next((t for t in tariffs if t.id == wanted_id), None)

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
        if tariffs and selected_tariff is None:
            flash('Оберіть тариф участі', 'error')
            return render_template(
                'registration/register.html',
                form=form, event=EventAdapter(instance),
                tariffs=tariffs, selected_tariff=None,
                profile_complete=bool(
                    current_user.medical_profile
                    and current_user.medical_profile.is_complete
                ),
            )
        if not verify_recaptcha(action='event_register'):
            flash('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.', 'error')
            return render_template(
                'registration/register.html',
                form=form, event=EventAdapter(instance),
                tariffs=tariffs, selected_tariff=selected_tariff,
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
            # 1) Слім-синхронізація: ПІБ у User + телефон у MedicalProfile.
            #    МОЗ-анкета живе в кабінеті (auth.certificate_data).
            _sync_medical_profile_from_form(current_user, form)

            # 2) Створити CourseRegistration. Снапшот МОЗ-полів -- з
            #    MedicalProfile, якщо той уже заповнений; інакше порожній
            #    (добере бекфіл, коли учасник заповнить "Дані для
            #    сертифіката" в кабінеті).
            profile = current_user.medical_profile
            specialty_snapshot = ''
            workplace_snapshot = ''
            if profile:
                specialty_snapshot = ', '.join(
                    _spec_labels(profile.specializations or [])
                ) or (profile.position or '').strip()
                workplace_snapshot = (profile.workplace or '').strip()
            form_data = {
                'phone': form.phone.data.strip(),
                'specialty': specialty_snapshot,
                'workplace': workplace_snapshot,
                'experience_years': None,
                'license_number': None,
            }
            from app.services import referral_service
            ref_code = referral_service.read_ref_cookie(request)
            # Не зараховуємо самореферал (код належить самому учаснику).
            if ref_code and current_user.referral_code == ref_code:
                ref_code = None
            reg, is_free = registration_service.create_or_reactivate(
                current_user.id, instance, form_data, existing,
                tariff=selected_tariff,
                referral_code=ref_code,
            )
            db.session.commit()
            # Аналітика воронки оплати: фіксуємо обраний спосіб і чи платна подія.
            logger.info(
                'Registration REG-%d created: user=%d instance=%d method=%s free=%s',
                reg.id, current_user.id, instance_id, reg.payment_method, is_free,
            )
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
                flash('Реєстрацію створено. Оберіть спосіб оплати нижче.', 'info')
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
        tariffs=tariffs,
        selected_tariff=selected_tariff,
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

    # Рахунок доступний поки реєстрацію не оплачено (і подія платна).
    invoice_available = (
        reg.payment_status != 'paid'
        and reg.payment_amount and reg.payment_amount > 0
    )

    profile = current_user.medical_profile
    return render_template(
        'registration/confirmation.html',
        reg=reg,
        event=template_event,
        liqpay_data=liqpay_data,
        liqpay_signature=liqpay_signature,
        liqpay_checkout_url=liqpay_checkout_url,
        invoice_available=bool(invoice_available),
        invoice_url=url_for('registration.invoice_download', registration_id=reg.id),
        certificate_data_complete=bool(profile and profile.is_complete),
    )


@registration_bp.route('/<int:registration_id>/invoice.pdf')
@login_required
def invoice_download(registration_id):
    """Завантаження PDF-рахунка учасником (власна реєстрація, поки не оплачено)."""
    reg = db.session.query(EventRegistration).options(
        joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
    ).filter_by(id=registration_id).first()
    if not reg or reg.user_id != current_user.id:
        abort(404)
    if not (reg.payment_amount and reg.payment_amount > 0):
        abort(404)
    if reg.payment_status == 'paid':
        flash('Реєстрацію вже оплачено — рахунок не потрібен.', 'info')
        return redirect(url_for('registration.confirmation', registration_id=reg.id))

    # Завантаження рахунка == вибір оплати за рахунком: фіксуємо фактичний
    # спосіб, щоб адмінка/аналітика відображали реальний вибір користувача.
    # Пропускаємо мутацію для prefetch/preload запитів браузера -- GET не має
    # мати side-effect для спекулятивних завантажень (PDF усе одно віддаємо).
    is_prefetch = 'prefetch' in (
        request.headers.get('Sec-Purpose', '')
        or request.headers.get('Purpose', '')
    ).lower()
    if reg.payment_method != 'invoice' and not is_prefetch:
        reg.payment_method = 'invoice'
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Failed to set payment_method=invoice for REG-%d', reg.id)

    from app.services.invoice_service import (
        InvoiceError, invoice_filename, render_invoice_pdf,
    )
    try:
        pdf = render_invoice_pdf(reg)
    except InvoiceError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('registration.confirmation', registration_id=reg.id))
    logger.info('Participant %s downloaded invoice for reg %d', current_user.id, reg.id)
    return send_file(
        io.BytesIO(pdf),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=invoice_filename(reg, 'pdf'),
        max_age=0,
    )


# ======================================================================
# Альтернативний pipeline: самостійне завершення реєстрації за токеном.
# Менеджер створює учасника з мінімумом полів і надсилає посилання; учасник
# заповнює повну анкету (усі поля обов'язкові) і обирає спосіб оплати.
# Публічні роути -- авторизація через сам токен (без login).
# ======================================================================

def _load_reg_by_token(token):
    return (
        db.session.query(EventRegistration)
        .options(
            joinedload(EventRegistration.user).joinedload(User.medical_profile),
            joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
        )
        .filter_by(completion_token=token)
        .first()
    )


@registration_bp.route('/complete/<token>', methods=['GET', 'POST'])
def complete_registration(token):
    """Публічна форма: учасник заповнює повну анкету за токеном-посиланням."""
    reg = _load_reg_by_token(token)
    if reg is None or not reg.completion_token_active:
        return render_template('registration/complete_invalid.html'), 410
    if reg.status == 'cancelled':
        return render_template('registration/complete_invalid.html', cancelled=True), 410

    instance = reg.instance
    user = reg.user
    profile = user.medical_profile if user else None

    if request.method == 'POST':
        form = ParticipantCompletionForm()
    else:
        raw_email = user.email if user else ''
        form = ParticipantCompletionForm(data={
            'user_type': (profile.participant_type if profile else '') or '',
            'last_name': (user.last_name if user else '') or '',
            'first_name': (user.first_name if user else '') or '',
            'middle_name': (profile.middle_name if profile else '') or '',
            'email': '' if participant_service.is_placeholder_email(raw_email) else raw_email,
            'phone': reg.phone or (profile.phone if profile else '') or '',
            'birth_date': profile.birth_date if profile else None,
            'education': (profile.education if profile else '') or '',
            'workplace': (profile.workplace if profile else '') or reg.workplace or '',
            'position': (profile.position if profile else '') or '',
            'specializations': (profile.specializations if profile else []) or [],
        })

    if form.validate_on_submit():
        data = {
            'instance_id': reg.instance_id,
            'last_name': form.last_name.data,
            'first_name': form.first_name.data,
            'middle_name': form.middle_name.data,
            'email': form.email.data,
            'phone': form.phone.data,
            'participant_type': form.user_type.data,
            'birth_date': form.birth_date.data,
            'education': form.education.data,
            'workplace': form.workplace.data,
            'position': form.position.data,
            'specializations': list(form.specializations.data or []),
            # Адмін-керовані поля -- зберігаємо як є (не даємо публіці їх міняти).
            'status': reg.status,
            'payment_status': reg.payment_status,
            'payment_amount': reg.payment_amount,
            'attended': reg.attended,
            'cpd_points_awarded': reg.cpd_points_awarded,
            'experience_years': reg.experience_years,
            'license_number': reg.license_number,
            'admin_notes': reg.admin_notes,
        }
        try:
            participant_service.upsert_participant(data, reg=reg)
        except ParticipantError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
        else:
            reg.completion_token_used_at = utcnow()
            db.session.commit()
            return redirect(url_for('registration.complete_payment', token=token))

    return render_template(
        'registration/complete.html',
        form=form,
        reg=reg,
        event=EventAdapter(instance) if instance else None,
    )


@registration_bp.route('/complete/<token>/pay')
def complete_payment(token):
    """Сторінка оплати: LiqPay або завантаження рахунка (PDF)."""
    reg = _load_reg_by_token(token)
    if reg is None or not reg.completion_token_active:
        return render_template('registration/complete_invalid.html'), 410

    # Повернення з LiqPay (?ret=1): онлайн-платіж міг ще не дійти вебхуком.
    # Best-effort опитуємо статус, щоб одразу показати банер підтвердження.
    # На відміну від payments.success цей роут публічний (авторизація --
    # сам токен), тож працює для учасника без логіну/пароля.
    if (request.args.get('ret') and reg.payment_amount and reg.payment_amount > 0
            and reg.payment_status in ('unpaid', 'pending')):
        from app.services.liqpay import get_liqpay_service
        from app.services.payment_ops import PaymentOps
        service = get_liqpay_service()
        if service.is_configured:
            try:
                PaymentOps(service).check_and_update(reg)
                db.session.refresh(reg)
            except Exception:
                logger.exception(
                    'Failed to poll LiqPay for REG-%d on complete_pay', reg.id,
                )

    liqpay_data = liqpay_signature = liqpay_checkout_url = None
    needs_payment = (
        reg.payment_status in ('unpaid', 'pending')
        and reg.payment_amount and reg.payment_amount > 0
    )
    if needs_payment:
        from app.services.liqpay import get_liqpay_service
        service = get_liqpay_service()
        if service.is_configured:
            order_id = f'REG-{reg.id}'
            # Публічний token-aware result_url: payments.success вимагає логіну,
            # а учасник у token-флоу не залогінений. ?ret=1 вмикає полінг статусу.
            result_url = url_for(
                'registration.complete_payment', token=token, ret=1, _external=True,
            )
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

    return render_template(
        'registration/complete_pay.html',
        reg=reg,
        event=EventAdapter(reg.instance) if reg.instance else None,
        needs_payment=bool(needs_payment),
        paid=(reg.payment_status == 'paid'),
        liqpay_data=liqpay_data,
        liqpay_signature=liqpay_signature,
        liqpay_checkout_url=liqpay_checkout_url,
        invoice_url=url_for('registration.complete_invoice', token=token),
    )


@registration_bp.route('/complete/<token>/invoice.pdf')
def complete_invoice(token):
    """Завантаження PDF-рахунка учасником (доступ за токеном)."""
    reg = _load_reg_by_token(token)
    if reg is None or not reg.completion_token_active:
        return render_template('registration/complete_invalid.html'), 410

    # Після оплати рахунок не потрібен (узгоджено з invoice_download).
    if reg.payment_status == 'paid':
        flash('Реєстрацію вже оплачено — рахунок не потрібен.', 'info')
        return redirect(url_for('registration.complete_payment', token=token))

    # Завантаження рахунка == вибір оплати за рахунком: фіксуємо реальний
    # спосіб (за замовчуванням 'liqpay'), щоб UX/аналітика/адмінка були точні.
    if reg.payment_method != 'invoice':
        reg.payment_method = 'invoice'
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Failed to set payment_method=invoice for REG-%d', reg.id)

    from app.services.invoice_service import (
        InvoiceError, invoice_filename, render_invoice_pdf,
    )
    try:
        pdf = render_invoice_pdf(reg)
    except InvoiceError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('registration.complete_payment', token=token))
    return send_file(
        io.BytesIO(pdf),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=invoice_filename(reg, 'pdf'),
        max_age=0,
    )
