import logging
import os
from datetime import datetime, timezone
from flask import render_template, redirect, url_for, flash, request, session, send_file
from flask_babel import get_locale, gettext as _
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.orm import contains_eager
from werkzeug.security import check_password_hash, generate_password_hash
from app.auth import auth_bp
from app.auth._helpers import is_safe_redirect_url
from app.auth.forms import (
    LoginForm, RegistrationForm, ForgotPasswordForm, ResetPasswordForm,
)
from app.extensions import db, limiter
from app.models.user import User
from app.models.auth_identity import AuthIdentity
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.certificate import Certificate
from app.services.token_service import (
    generate_confirmation_token, confirm_token,
    generate_password_reset_token, confirm_password_reset_token,
)
from app.services.email_service import EmailService
from app.services.recaptcha import verify_request as verify_recaptcha

logger = logging.getLogger(__name__)

# Фіктивний хеш для вирівнювання часу відповіді, коли акаунта з такою
# адресою немає: без нього відповідь на неіснуючий email поверталась би
# помітно швидше (пропускалась перевірка хеша) -- це піддається вимірюванню
# і дає user enumeration. Обчислюється один раз при імпорті.
_DUMMY_PASSWORD_HASH = generate_password_hash('timing-equalizer')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=['POST'])
@limiter.limit("20 per hour", methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.account'))

    form = LoginForm()
    if form.validate_on_submit():
        if not verify_recaptcha(action='login'):
            flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
            return render_template('auth/login.html', form=form)

        # Identity-first lookup (Phase 2): пароль живе ЛИШЕ у
        # AuthIdentity(provider='password'), тож відсутність identity
        # означає відсутність пароля -- окремий fallback на User не
        # потрібен (він однаково не зміг би автентифікувати).
        email = form.email.data.lower().strip()
        identity = AuthIdentity.find_password_identity_by_email(email)
        if identity is not None:
            password_ok = identity.check_password(form.password.data)
        else:
            check_password_hash(_DUMMY_PASSWORD_HASH, form.password.data)
            password_ok = False

        if password_ok and not identity.user.is_active:
            # login_user() сам відмовив би деактивованому юзеру, але мовчки
            # (повертає False), і далі був би редірект на /auth/account ->
            # @login_required -> назад на логін. Кажемо прямо.
            flash(_('Обліковий запис деактивовано'), 'error')
            return render_template('auth/login.html', form=form)

        if password_ok:
            user = identity.user
            session.clear()
            login_user(user, remember=form.remember.data)
            user.last_login_at = datetime.now(timezone.utc)
            identity.touch()

            try:
                db.session.commit()
            except Exception:
                logger.exception('Failed to update last_login_at for user %s', user.id)
                db.session.rollback()

            next_page = request.args.get('next')
            if is_safe_redirect_url(next_page):
                return redirect(next_page)
            return redirect(url_for('auth.account'))

        flash(_('Невірний email або пароль'), 'error')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("3 per hour", methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('auth.account'))

    form = RegistrationForm()
    if form.validate_on_submit():
        if not verify_recaptcha(action='register'):
            flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
            return render_template('auth/register.html', form=form)
        # Phase 2: фабрика створює User + password-identity + порожній
        # MedicalProfile у одній транзакції. Identity-row буде використано
        # для логіну, MedicalProfile -- для gate-у на event-registration.
        user = User.create_with_password(
            email=form.email.data,
            password=form.password.data,
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
        )
        # Мова листів = мова інтерфейсу при самореєстрації (uk = NULL).
        ui_lang = str(get_locale() or '')
        if ui_lang and ui_lang != 'uk':
            user.preferred_language = ui_lang

        try:
            db.session.commit()
            session.clear()
            login_user(user)

            email_sent = False
            try:
                token = generate_confirmation_token(user.id)
                confirm_url = url_for('auth.confirm_email', token=token, _external=True)
                EmailService.send_email_confirmation(user, confirm_url)
                email_sent = True
            except Exception:
                logger.exception('Failed to send confirmation email to %s', user.email)

            if email_sent:
                flash(_('Реєстрацію завершено. Перевірте email для підтвердження.'), 'info')
            else:
                flash(_('Реєстрацію завершено. Натисніть "Надіслати лист повторно" у кабінеті для підтвердження email.'), 'warning')
            return redirect(url_for('auth.account'))
        except Exception:
            logger.exception('Failed to register user %s', form.email.data)
            db.session.rollback()
            flash(_('Помилка при реєстрації'), 'error')

    return render_template('auth/register.html', form=form)


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit('5 per hour', methods=['POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('auth.account'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        if not verify_recaptcha(action='forgot_password'):
            flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
            return render_template('auth/forgot_password.html', form=form)

        email = form.email.data.lower().strip()
        user = User.query.filter_by(email=email).first()
        if user and user.is_active:
            try:
                token = generate_password_reset_token(user.id)
                reset_url = url_for('auth.reset_password', token=token, _external=True)
                EmailService.send_password_reset(user, reset_url)
            except Exception:
                logger.exception('Failed to send password reset to %s', email)

        # Anti-enumeration: відповідь однакова незалежно від існування акаунта.
        flash(_('Якщо акаунт з такою адресою існує, ми надіслали лист з '
                'інструкціями для відновлення паролю.'), 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html', form=form)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
@limiter.limit('10 per hour', methods=['POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('auth.account'))

    user_id = confirm_password_reset_token(token)
    user = db.session.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        flash(_('Посилання недійсне або термін його дії минув. Спробуйте ще раз.'), 'error')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        # Клік за лінком, надісланим на email, підтверджує володіння адресою.
        user.email_confirmed = True
        user.set_password(form.password.data)
        try:
            db.session.commit()
        except Exception:
            logger.exception('Failed to reset password for user %s', user.id)
            db.session.rollback()
            flash(_('Помилка при збереженні паролю. Спробуйте ще раз.'), 'error')
            return render_template('auth/reset_password.html', form=form, token=token)

        flash(_('Пароль успішно змінено. Тепер ви можете увійти.'), 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', form=form, token=token)


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    # logout_user() прибирає лише ключі Flask-Login. Чистимо решту сесії
    # (незавершені OAuth-флоу, контекст колізії), зберігши вибір мови --
    # він не пов'язаний з обліковим записом.
    lang = session.get('lang')
    session.clear()
    if lang:
        session['lang'] = lang
    return redirect(url_for('main.index'))


@auth_bp.route('/account')
@login_required
def account():
    registrations = (
        EventRegistration.query
        .filter_by(user_id=current_user.id)
        .filter(EventRegistration.status != 'cancelled')
        .join(CourseInstance, EventRegistration.instance_id == CourseInstance.id)
        .options(contains_eager(EventRegistration.instance).joinedload(CourseInstance.course))
        .order_by(CourseInstance.start_date.desc())
        .all()
    )
    certificates = (
        Certificate.query
        .filter_by(user_id=current_user.id, revoked=False)
        .order_by(Certificate.issued_at.desc())
        .all()
    )
    profile = current_user.medical_profile

    # Реферальна програма (показуємо блок лише коли увімкнено). Код
    # генерується лениво при першому відкритті кабінету.
    from app.models.site_settings import SiteSettings
    from app.services import referral_service
    settings = SiteSettings.get()
    referral_link = None
    referral_qr = None
    referral_balance = 0
    referral_pending = 0
    referral_rewards = []
    if settings.referral_enabled:
        had_code = bool(current_user.referral_code)
        referral_link = referral_service.user_referral_link(current_user)
        if not had_code:  # код щойно згенеровано -> зберегти
            db.session.commit()
        referral_qr = referral_service.qr_svg(referral_link)
        referral_balance = referral_service.get_balance('user', current_user.id)
        referral_pending = referral_service.get_pending_balance('user', current_user.id)
        referral_rewards = referral_service.list_referrer_rewards('user', current_user.id)

    return render_template(
        'auth/account.html',
        registrations=registrations,
        certificates=certificates,
        certificate_data_complete=bool(profile and profile.is_complete),
        referral_link=referral_link,
        referral_qr=referral_qr,
        referral_balance=referral_balance,
        referral_pending=referral_pending,
        referral_rewards=referral_rewards,
    )


@auth_bp.route('/account/certificate-data', methods=['GET', 'POST'])
@login_required
def certificate_data():
    """Анкета "Дані для сертифіката" (МОЗ №725 п.13).

    Винесена за рамки flow реєстрації/оплати (рішення 08.07.2026):
    учасник заповнює її тут, щоб отримати сертифікат з балами БПР.
    Після збереження бекфілимо порожні снапшоти specialty/workplace
    в активних реєстраціях (для звітів БПР/xlsx).
    """
    from app.auth.forms import CertificateDataForm
    from app.models.medical_profile import MedicalProfile
    from app.models.specializations import labels_for_codes

    profile = current_user.medical_profile

    if request.method == 'GET':
        form = CertificateDataForm(data={
            'user_type': (profile.participant_type if profile else '') or '',
            'middle_name': (profile.middle_name if profile else '') or '',
            'birth_date': profile.birth_date if profile else None,
            'education': (profile.education if profile else '') or '',
            'workplace': (profile.workplace if profile else '') or '',
            'position': (profile.position if profile else '') or '',
            'specializations': (profile.specializations if profile else []) or [],
        })
    else:
        form = CertificateDataForm()

    if form.validate_on_submit():
        if profile is None:
            profile = MedicalProfile(
                user_id=current_user.id, source=MedicalProfile.SOURCE_SELF,
            )
            db.session.add(profile)
            current_user.medical_profile = profile
        profile.participant_type = form.user_type.data
        profile.middle_name = (form.middle_name.data or '').strip() or None
        profile.birth_date = form.birth_date.data
        profile.education = (form.education.data or '').strip() or None
        profile.workplace = (form.workplace.data or '').strip() or None
        profile.position = (form.position.data or '').strip() or None
        profile.specializations = list(form.specializations.data or [])
        if profile.is_complete and profile.completed_at is None:
            profile.completed_at = datetime.now(timezone.utc)

        specialty_snapshot = ', '.join(
            labels_for_codes(profile.specializations or [])
        ) or (profile.position or '').strip()
        workplace_snapshot = (profile.workplace or '').strip()
        regs = (
            EventRegistration.query
            .filter(
                EventRegistration.user_id == current_user.id,
                EventRegistration.status != 'cancelled',
            )
            .all()
        )
        for reg in regs:
            if not (reg.specialty or '').strip() and specialty_snapshot:
                reg.specialty = specialty_snapshot
            if not (reg.workplace or '').strip() and workplace_snapshot:
                reg.workplace = workplace_snapshot

        backfilled = sum(
            1 for reg in regs
            if reg.specialty == specialty_snapshot or reg.workplace == workplace_snapshot
        )
        try:
            db.session.commit()
            logger.info(
                'Certificate data saved: user=%d complete=%s backfilled_regs=%d',
                current_user.id, profile.is_complete, backfilled,
            )
            flash(_('Дані для сертифіката збережено. Дякуємо!'), 'success')
            return redirect(url_for('auth.account'))
        except Exception:
            db.session.rollback()
            logger.exception(
                'Failed to save certificate data for user %d', current_user.id,
            )
            flash(_('Помилка при збереженні. Спробуйте ще раз.'), 'error')

    return render_template('auth/certificate_data.html', form=form)


@auth_bp.route('/account/certificates/<int:cert_id>/download')
@login_required
def certificate_download(cert_id):
    """Завантажити власний сертифікат (перевірка володіння)."""
    cert = db.session.get(Certificate, cert_id)
    if cert is None or cert.user_id != current_user.id or cert.revoked:
        flash(_('Сертифікат не знайдено'), 'error')
        return redirect(url_for('auth.account'))

    from app.services.certificate_service import certificate_abs_path, regenerate_pdf
    path = certificate_abs_path(cert)
    if not os.path.exists(path):
        try:
            regenerate_pdf(cert)
        except Exception:
            logger.exception('Failed to regenerate certificate PDF %s', cert.number)
        if not os.path.exists(path):
            # Краще зрозуміле повідомлення в кабінеті, ніж 500 від send_file.
            flash(_('Не вдалося підготувати PDF. Спробуйте пізніше або '
                    'зверніться до підтримки.'), 'error')
            return redirect(url_for('auth.account'))
    return send_file(
        path,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{cert.number}.pdf',
    )


@auth_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        from app.i18n import LANGUAGES
        lang = request.form.get('email_language', 'uk')
        if lang not in LANGUAGES:
            lang = 'uk'
        # uk -- вихідна мова, зберігаємо як NULL (див. User.preferred_language).
        current_user.preferred_language = None if lang == 'uk' else lang
        try:
            db.session.commit()
            flash(_('Налаштування збережено'), 'success')
        except Exception:
            logger.exception('Failed to save email language for user %s', current_user.id)
            db.session.rollback()
            flash(_('Помилка при збереженні налаштувань'), 'error')
        return redirect(url_for('auth.settings'))
    return render_template('auth/settings.html')


@auth_bp.route('/account/connections')
@login_required
def connections():
    """Перелік прив'язаних identity-провайдерів + link/unlink дії.
    Власник цієї сторінки -- сам юзер. Адмін не керує чужими identity."""
    idents = AuthIdentity.query.filter_by(user_id=current_user.id).all()
    by_provider = {i.provider: i for i in idents}
    pw_identity = by_provider.get(AuthIdentity.PROVIDER_PASSWORD)
    # Саме наявність хеша, а не рядка identity: порожня password-identity
    # входу не дає, і кнопка "Встановити пароль" має лишатись доступною.
    has_password = bool(pw_identity and pw_identity.password_hash)
    has_google = AuthIdentity.PROVIDER_GOOGLE in by_provider
    has_apple = AuthIdentity.PROVIDER_APPLE in by_provider
    return render_template(
        'auth/connections.html',
        identities=idents,
        by_provider=by_provider,
        has_password=has_password,
        has_google=has_google,
        has_apple=has_apple,
        google_oauth_available=_google_oauth_available(),
        apple_signin_available=_apple_signin_available(),
    )


@auth_bp.route('/account/set-password', methods=['GET', 'POST'])
@login_required
@limiter.limit('5 per hour', methods=['POST'])
def set_password():
    """Встановити пароль акаунту, у якого його ще немає (вхід лише через
    OAuth або імпортований учасник).

    Поточний пароль не питаємо -- його немає. Доступ до сесії вже є
    доказом володіння акаунтом. Якщо пароль ВЖЕ встановлено, змінювати
    його тут не можна: це вимагало б підтвердження старого пароля, для
    чого є окремий флоу "Забули пароль".
    """
    has_password = AuthIdentity.query.filter(
        AuthIdentity.user_id == current_user.id,
        AuthIdentity.provider == AuthIdentity.PROVIDER_PASSWORD,
        AuthIdentity.password_hash.isnot(None),
    ).first() is not None
    if has_password:
        flash(_('Пароль уже встановлено. Щоб змінити його, скористайтесь '
                'відновленням паролю.'), 'info')
        return redirect(url_for('auth.connections'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        current_user.set_password(form.password.data)
        try:
            db.session.commit()
            logger.info('Password set for user %d', current_user.id)
            flash(_('Пароль встановлено. Тепер ви можете входити з email і паролем.'),
                  'success')
            return redirect(url_for('auth.connections'))
        except Exception:
            db.session.rollback()
            logger.exception('Failed to set password for user %d', current_user.id)
            flash(_('Помилка при збереженні паролю. Спробуйте ще раз.'), 'error')

    return render_template('auth/set_password.html', form=form)


def _google_oauth_available():
    from app.models.site_settings import SiteSettings
    return SiteSettings.get().is_google_oauth_configured


def _apple_signin_available():
    from app.models.site_settings import SiteSettings
    return SiteSettings.get().is_apple_signin_configured


@auth_bp.route('/confirm/<token>')
@limiter.limit('10 per minute')
def confirm_email(token):
    user_id = confirm_token(token)
    if user_id is None:
        flash(_('Посилання недійсне або прострочене. Запросіть нове.'), 'error')
        return redirect(url_for('auth.login'))

    user = db.session.get(User, user_id)
    if not user:
        flash(_('Користувача не знайдено'), 'error')
        return redirect(url_for('auth.login'))

    if user.email_confirmed:
        flash(_('Email вже підтверджено'), 'info')
    else:
        user.email_confirmed = True
        try:
            db.session.commit()
            flash(_('Email успішно підтверджено!'), 'success')
            logger.info('Email confirmed for user %d', user.id)
        except Exception:
            db.session.rollback()
            logger.exception('Failed to confirm email for user %d', user.id)
            flash(_('Помилка при підтвердженні'), 'error')

    if current_user.is_authenticated:
        return redirect(url_for('auth.account'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/resend-confirmation', methods=['POST'])
@login_required
@limiter.limit('3 per hour')
def resend_confirmation():
    if current_user.email_confirmed:
        flash(_('Email вже підтверджено'), 'info')
        return redirect(url_for('auth.account'))

    if not verify_recaptcha(action='resend_confirmation'):
        flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
        return redirect(url_for('auth.account'))

    try:
        token = generate_confirmation_token(current_user.id)
        confirm_url = url_for('auth.confirm_email', token=token, _external=True)
        EmailService.send_email_confirmation(current_user, confirm_url)
        flash(_('Лист з підтвердженням надіслано повторно'), 'success')
    except Exception:
        logger.exception('Failed to resend confirmation to %s', current_user.email)
        flash(_('Не вдалося надіслати лист'), 'error')

    return redirect(url_for('auth.account'))
