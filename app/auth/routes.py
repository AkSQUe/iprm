import logging
from datetime import datetime, timezone
from urllib.parse import urlparse
from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.orm import contains_eager
from app.auth import auth_bp
from app.auth.forms import LoginForm, RegistrationForm
from app.extensions import db, limiter
from app.models.user import User
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.services.token_service import generate_confirmation_token, confirm_token
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


def _is_safe_redirect_url(target):
    if not target:
        return False
    parsed = urlparse(target)
    return (not parsed.netloc and not parsed.scheme
            and target.startswith('/') and not target.startswith('//'))


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=['POST'])
@limiter.limit("20 per hour", methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.account'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()

        if user and user.check_password(form.password.data):
            session.clear()
            login_user(user, remember=form.remember.data)
            user.last_login_at = datetime.now(timezone.utc)

            try:
                db.session.commit()
            except Exception:
                logger.exception('Failed to update last_login_at for user %s', user.id)
                db.session.rollback()

            next_page = request.args.get('next')
            if _is_safe_redirect_url(next_page):
                return redirect(next_page)
            return redirect(url_for('auth.account'))

        flash('Невірний email або пароль', 'error')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("3 per hour", methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('auth.account'))

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            email=form.email.data,
            password=form.password.data,
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
        )
        db.session.add(user)

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
                flash('Реєстрацію завершено. Перевірте email для підтвердження.', 'info')
            else:
                flash('Реєстрацію завершено. Натисніть "Надіслати лист повторно" у кабінеті для підтвердження email.', 'warning')
            return redirect(url_for('auth.account'))
        except Exception:
            logger.exception('Failed to register user %s', form.email.data)
            db.session.rollback()
            flash('Помилка при реєстрації', 'error')

    return render_template('auth/register.html', form=form)


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
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
    return render_template('auth/account.html', registrations=registrations)


@auth_bp.route('/settings')
@login_required
def settings():
    return render_template('auth/settings.html')


@auth_bp.route('/confirm/<token>')
@limiter.limit('10 per minute')
def confirm_email(token):
    user_id = confirm_token(token)
    if user_id is None:
        flash('Посилання недійсне або прострочене. Запросіть нове.', 'error')
        return redirect(url_for('auth.login'))

    user = db.session.get(User, user_id)
    if not user:
        flash('Користувача не знайдено', 'error')
        return redirect(url_for('auth.login'))

    if user.email_confirmed:
        flash('Email вже підтверджено', 'info')
    else:
        user.email_confirmed = True
        try:
            db.session.commit()
            flash('Email успішно підтверджено!', 'success')
            logger.info('Email confirmed for user %d', user.id)
        except Exception:
            db.session.rollback()
            logger.exception('Failed to confirm email for user %d', user.id)
            flash('Помилка при підтвердженні', 'error')

    if current_user.is_authenticated:
        return redirect(url_for('auth.account'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/resend-confirmation', methods=['POST'])
@login_required
@limiter.limit('3 per hour')
def resend_confirmation():
    if current_user.email_confirmed:
        flash('Email вже підтверджено', 'info')
        return redirect(url_for('auth.account'))

    try:
        token = generate_confirmation_token(current_user.id)
        confirm_url = url_for('auth.confirm_email', token=token, _external=True)
        EmailService.send_email_confirmation(current_user, confirm_url)
        flash('Лист з підтвердженням надіслано повторно', 'success')
    except Exception:
        logger.exception('Failed to resend confirmation to %s', current_user.email)
        flash('Не вдалося надіслати лист', 'error')

    return redirect(url_for('auth.account'))
