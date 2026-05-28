"""OAuth routes (Phase 3 of auth unification).

Зараз реалізовано Google; Apple буде в Phase 5 з тим самим патерном.
Routes:
  GET /auth/google/start            -- редірект на Google authorize endpoint
  GET /auth/google/callback         -- exchange code, lookup/create/link user
  POST /auth/google/link/start      -- (логін потрібен) почати link-flow
  POST /auth/google/unlink          -- (логін потрібен) видалити Google identity

Callback розв'язує 3 сценарії:
  1. Знайдено identity (provider='google', sub=token.sub) -> логін.
  2. Не знайдено, але email вже зайнятий password-identity у нашій БД
     -> show "цей email вже зареєстровано; увійдіть паролем і прив'яжіть
     Google в кабінеті". НЕ зливаємо автоматично (захист від OAuth-
     based account takeover; рекомендація OWASP).
  3. Інакше -- створюємо новий User через User.create_with_oauth().
     email_verified Google завжди true для @gmail.com, але перевіряємо
     claim явно (для Workspace доменів інколи буває false).

Link-flow:
  - Юзер залогінений password-ом, заходить на /auth/account/connections,
    клікає "Link Google" -> POST /auth/google/link/start -> сесія
    позначається link-action=true -> /auth/google/start виконує redirect.
  - У callback при link-action=true: lookup identity (provider, sub).
    Якщо вже належить ІНШОМУ юзеру -> error. Інакше -- створюємо
    identity з user_id=current_user.id.
"""
import logging
import secrets

from authlib.integrations.base_client.errors import OAuthError
from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, session, url_for,
)
from flask_login import current_user, login_required, login_user

from app.auth import auth_bp
from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.user import User
from app.services.google_oauth import get_google_client

logger = logging.getLogger(__name__)

# Session keys
SESSION_OAUTH_STATE = '_oauth_state'
SESSION_OAUTH_NEXT = '_oauth_next'
SESSION_OAUTH_ACTION = '_oauth_action'   # 'login' (default) | 'link'

ACTION_LOGIN = 'login'
ACTION_LINK = 'link'


def _is_safe_redirect_url(target):
    """Same logic as auth.routes -- DRY by reimporting? Тримаємо тут
    локально щоб уникнути циклічного імпорту."""
    if not target:
        return False
    from urllib.parse import urlparse
    parsed = urlparse(target)
    return (not parsed.netloc and not parsed.scheme
            and target.startswith('/') and not target.startswith('//'))


@auth_bp.route('/google/start', methods=['GET'])
def google_start():
    """Початок OAuth-flow. action=login (default) або action=link
    (за наявності query-string ?action=link І залогіненого юзера)."""
    client = get_google_client()
    if client is None:
        flash('Google вхід наразі не налаштовано', 'error')
        return redirect(url_for('auth.login'))

    action = request.args.get('action', ACTION_LOGIN)
    if action == ACTION_LINK and not current_user.is_authenticated:
        # link-flow вимагає вже залогіненого юзера
        return redirect(url_for('auth.login'))

    # Збережемо action і next URL у сесії -- callback їх прочитає.
    session[SESSION_OAUTH_ACTION] = action
    next_url = request.args.get('next', '')
    if _is_safe_redirect_url(next_url):
        session[SESSION_OAUTH_NEXT] = next_url
    else:
        session.pop(SESSION_OAUTH_NEXT, None)

    redirect_uri = url_for('auth.google_callback', _external=True)
    return client.authorize_redirect(redirect_uri)


@auth_bp.route('/google/callback', methods=['GET'])
def google_callback():
    """Обробка повернення з Google. Витягуємо OIDC-claims через Authlib
    (валідація state/nonce/підпису -- автоматично). Далі -- три гілки:
    existing identity / email-collision / new user."""
    client = get_google_client()
    if client is None:
        flash('Google вхід наразі не налаштовано', 'error')
        return redirect(url_for('auth.login'))

    try:
        token = client.authorize_access_token()
    except OAuthError as exc:
        logger.warning('Google OAuth error: %s', exc.error)
        flash('Помилка автентифікації через Google. Спробуйте ще раз.', 'error')
        return redirect(url_for('auth.login'))

    # Authlib повертає id_token-claims у token['userinfo'] (декодовано
    # і провалідовано). Fallback на UserInfo endpoint, якщо чомусь нема.
    userinfo = token.get('userinfo') or client.userinfo(token=token)
    sub = userinfo.get('sub')
    email = (userinfo.get('email') or '').lower().strip()
    email_verified = bool(userinfo.get('email_verified'))
    given_name = userinfo.get('given_name')
    family_name = userinfo.get('family_name')

    if not sub or not email:
        logger.warning('Google OAuth: missing sub or email in userinfo: %s', userinfo)
        flash('Google не повернув необхідні дані. Спробуйте ще раз.', 'error')
        return redirect(url_for('auth.login'))

    # Зберігаємо лише мінімальні claims (GDPR-friendly):
    safe_claims = {
        k: userinfo.get(k) for k in
        ('sub', 'email', 'email_verified', 'given_name', 'family_name', 'locale')
        if userinfo.get(k) is not None
    }

    action = session.pop(SESSION_OAUTH_ACTION, ACTION_LOGIN)
    next_url = session.pop(SESSION_OAUTH_NEXT, None)

    if action == ACTION_LINK:
        return _handle_link(sub, email, email_verified, safe_claims, next_url)
    return _handle_login(sub, email, email_verified, given_name, family_name,
                         safe_claims, next_url)


def _handle_login(sub, email, email_verified, given_name, family_name,
                  safe_claims, next_url):
    """Гілка login: знайти identity або створити нового User."""
    identity = AuthIdentity.find_by_provider_sub(
        AuthIdentity.PROVIDER_GOOGLE, sub,
    )

    if identity:
        # Існуюча Google-identity -- логінимо власника.
        user = identity.user
        if not user.is_active:
            flash('Обліковий запис деактивовано', 'error')
            return redirect(url_for('auth.login'))
        identity.email = email
        identity.email_verified = email_verified
        identity.raw_claims = safe_claims
        identity.touch()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Failed to update identity on Google login')

        session.clear()
        login_user(user, remember=True)
        if next_url and _is_safe_redirect_url(next_url):
            return redirect(next_url)
        return redirect(url_for('auth.account'))

    # Identity не знайдено -- перевіряємо email-collision.
    existing_pw_identity = AuthIdentity.find_password_identity_by_email(email)
    if existing_pw_identity:
        # OWASP: НЕ зливаємо автоматично. Показуємо інструкцію.
        return render_template(
            'auth/oauth_email_collision.html',
            email=email,
            provider='Google',
        )

    # Жодних збігів -- створюємо нового User через OAuth-фабрику.
    try:
        user = User.create_with_oauth(
            provider=AuthIdentity.PROVIDER_GOOGLE,
            sub=sub,
            email=email,
            email_verified=email_verified,
            first_name=given_name,
            last_name=family_name,
            raw_claims=safe_claims,
        )
        db.session.commit()
        logger.info('Created Google OAuth user id=%d email=%s', user.id, user.email)
    except Exception:
        db.session.rollback()
        logger.exception('Failed to create Google OAuth user')
        flash('Помилка при створенні облікового запису', 'error')
        return redirect(url_for('auth.login'))

    session.clear()
    login_user(user, remember=True)
    flash('Вітаємо! Обліковий запис створено через Google.', 'success')
    if next_url and _is_safe_redirect_url(next_url):
        return redirect(next_url)
    return redirect(url_for('auth.account'))


def _handle_link(sub, email, email_verified, safe_claims, next_url):
    """Гілка link: прив'язати Google identity до current_user. Захист від
    спроби прив'язати identity, що вже належить іншому юзеру."""
    if not current_user.is_authenticated:
        # Сесія могла протухнути між /start і callback.
        return redirect(url_for('auth.login'))

    existing = AuthIdentity.find_by_provider_sub(
        AuthIdentity.PROVIDER_GOOGLE, sub,
    )
    if existing:
        if existing.user_id == current_user.id:
            flash('Google вже прив\'язано до вашого облікового запису', 'info')
        else:
            # Цей Google-акаунт вже належить іншому юзеру нашої системи.
            flash(
                'Цей Google-акаунт вже прив\'язано до іншого облікового '
                'запису. Зв\'яжіться з підтримкою для допомоги.',
                'error',
            )
        return redirect(url_for('auth.connections'))

    db.session.add(AuthIdentity(
        user_id=current_user.id,
        provider=AuthIdentity.PROVIDER_GOOGLE,
        provider_sub=str(sub),
        email=email,
        email_verified=email_verified,
        raw_claims=safe_claims,
    ))
    try:
        db.session.commit()
        flash('Google успішно прив\'язано до вашого облікового запису', 'success')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to link Google identity')
        flash('Помилка при прив\'язці Google', 'error')

    return redirect(url_for('auth.connections'))


@auth_bp.route('/google/unlink', methods=['POST'])
@login_required
def google_unlink():
    """Видалити Google identity у поточного юзера. Захист: не дозволяємо
    видалити останню identity (інакше юзер втратить доступ)."""
    identity = AuthIdentity.query.filter_by(
        user_id=current_user.id,
        provider=AuthIdentity.PROVIDER_GOOGLE,
    ).first()
    if not identity:
        flash('Google не прив\'язано', 'info')
        return redirect(url_for('auth.connections'))

    total = AuthIdentity.query.filter_by(user_id=current_user.id).count()
    if total <= 1:
        flash(
            'Не можна видалити останній спосіб входу. Спочатку встановіть '
            'пароль або прив\'яжіть інший провайдер.',
            'error',
        )
        return redirect(url_for('auth.connections'))

    db.session.delete(identity)
    try:
        db.session.commit()
        flash('Google від\'єднано від вашого облікового запису', 'success')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to unlink Google identity')
        flash('Помилка при від\'єднанні', 'error')

    return redirect(url_for('auth.connections'))
