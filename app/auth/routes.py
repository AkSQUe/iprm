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
from app.models.event import Event
from app.models.registration import EventRegistration

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
        .join(Event)
        .options(contains_eager(EventRegistration.event))
        .order_by(Event.start_date.desc())
        .all()
    )
    return render_template('auth/account.html', registrations=registrations)
