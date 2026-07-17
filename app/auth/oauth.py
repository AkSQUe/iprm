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
from app.extensions import db, csrf
from app.models.auth_identity import AuthIdentity
from app.models.user import User
from app.services.google_oauth import get_google_client, verify_google_id_token
from app.services.apple_signin import get_apple_client

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
        # Діагностика: чи дійшов state у сесії (cookie не згубився). Якщо
        # state_arg=True, а had_state=False -> сесія-cookie не долетіла до
        # callback (SameSite/домен www vs apex/схема http vs https або
        # canonical-редірект між /start і /callback), а не помилка коду.
        had_state = any(k.startswith('_state_google_') for k in session.keys())
        logger.warning(
            'Google OAuth error: %s (%s); state_in_session=%s state_arg=%s',
            exc.error, getattr(exc, 'description', '') or '',
            had_state, bool(request.args.get('state')),
        )
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
        return _handle_link(
            AuthIdentity.PROVIDER_GOOGLE,
            sub, email, email_verified, safe_claims, next_url,
        )
    return _handle_login(
        AuthIdentity.PROVIDER_GOOGLE,
        sub, email, email_verified, given_name, family_name,
        safe_claims, next_url,
    )


# Людино-читні назви для flash-меседжів і collision-сторінки.
PROVIDER_LABELS = {
    AuthIdentity.PROVIDER_GOOGLE: 'Google',
    AuthIdentity.PROVIDER_APPLE: 'Apple',
}


def _handle_login(provider, sub, email, email_verified, given_name, family_name,
                  safe_claims, next_url):
    """Гілка login: знайти identity або створити нового User. Працює
    для будь-якого OAuth/OIDC-провайдера (Google, Apple, ...) -- різниця
    лише у назві провайдера та у текстах повідомлень."""
    label = PROVIDER_LABELS.get(provider, provider)
    identity = AuthIdentity.find_by_provider_sub(provider, sub)

    if identity:
        user = identity.user
        if not user.is_active:
            flash('Обліковий запис деактивовано', 'error')
            return redirect(url_for('auth.login'))
        if email:
            identity.email = email
        identity.email_verified = email_verified
        identity.raw_claims = safe_claims
        identity.touch()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Failed to update identity on %s login', label)

        session.clear()
        login_user(user, remember=True)
        if next_url and _is_safe_redirect_url(next_url):
            return redirect(next_url)
        return redirect(url_for('auth.account'))

    # Identity не знайдено -- перевіряємо email-collision.
    existing_pw_identity = (
        AuthIdentity.find_password_identity_by_email(email) if email else None
    )
    if existing_pw_identity:
        # OWASP: НЕ зливаємо автоматично. Показуємо інструкцію.
        return render_template(
            'auth/oauth_email_collision.html',
            email=email,
            provider=label,
        )

    # Жодних збігів -- створюємо нового User через OAuth-фабрику.
    try:
        user = User.create_with_oauth(
            provider=provider,
            sub=sub,
            email=email,
            email_verified=email_verified,
            first_name=given_name,
            last_name=family_name,
            raw_claims=safe_claims,
        )
        db.session.commit()
        logger.info('Created %s OAuth user id=%d email=%s', label, user.id, user.email)
    except Exception:
        db.session.rollback()
        logger.exception('Failed to create %s OAuth user', label)
        flash('Помилка при створенні облікового запису', 'error')
        return redirect(url_for('auth.login'))

    session.clear()
    login_user(user, remember=True)
    flash(f'Вітаємо! Обліковий запис створено через {label}.', 'success')
    if next_url and _is_safe_redirect_url(next_url):
        return redirect(next_url)
    return redirect(url_for('auth.account'))


def _handle_link(provider, sub, email, email_verified, safe_claims, next_url):
    """Гілка link: прив'язати OAuth identity до current_user. Захист від
    спроби прив'язати identity, що вже належить іншому юзеру."""
    label = PROVIDER_LABELS.get(provider, provider)
    if not current_user.is_authenticated:
        # Сесія могла протухнути між /start і callback.
        return redirect(url_for('auth.login'))

    existing = AuthIdentity.find_by_provider_sub(provider, sub)
    if existing:
        if existing.user_id == current_user.id:
            flash(f'{label} вже прив\'язано до вашого облікового запису', 'info')
        else:
            flash(
                f'Цей {label}-акаунт вже прив\'язано до іншого облікового '
                'запису. Зв\'яжіться з підтримкою для допомоги.',
                'error',
            )
        return redirect(url_for('auth.connections'))

    db.session.add(AuthIdentity(
        user_id=current_user.id,
        provider=provider,
        provider_sub=str(sub),
        email=email,
        email_verified=email_verified,
        raw_claims=safe_claims,
    ))
    try:
        db.session.commit()
        flash(f'{label} успішно прив\'язано до вашого облікового запису', 'success')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to link Google identity')
        flash('Помилка при прив\'язці Google', 'error')

    return redirect(url_for('auth.connections'))


def _unlink_provider(provider):
    """Спільний helper для unlink-роутів. Не дозволяє видалити останню
    identity (захист від втрати доступу)."""
    label = PROVIDER_LABELS.get(provider, provider)
    identity = AuthIdentity.query.filter_by(
        user_id=current_user.id,
        provider=provider,
    ).first()
    if not identity:
        flash(f'{label} не прив\'язано', 'info')
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
        flash(f'{label} від\'єднано від вашого облікового запису', 'success')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to unlink %s identity', label)
        flash('Помилка при від\'єднанні', 'error')

    return redirect(url_for('auth.connections'))


@auth_bp.route('/google/unlink', methods=['POST'])
@login_required
def google_unlink():
    return _unlink_provider(AuthIdentity.PROVIDER_GOOGLE)


# =============================================================
# Google One Tap (Phase 6)
# =============================================================

@auth_bp.route('/google/onetap', methods=['POST'])
@csrf.exempt
def google_onetap():
    """Прийом credential JWT від Google One Tap (GSI library).

    JWT уже містить підпис Google + state-binding (nonce), тож CSRF-захист
    не потрібен -- сам credential і є аутентифікація запиту.

    Логіка lookup-or-create -- паралельна _handle_login() з redirect-flow,
    але без HTTP-redirect (повертаємо JSON, фронт сам редіректить).
    email-collision -- НЕ зливаємо автоматично; повертаємо 409 + URL
    логіну для ручної прив'язки.
    """
    from flask import jsonify
    from app.models.site_settings import SiteSettings

    settings = SiteSettings.get()
    if not settings.is_google_oauth_configured:
        return jsonify({'ok': False, 'error': 'not_configured'}), 503

    data = request.get_json(silent=True) or {}
    credential = data.get('credential')
    if not credential:
        return jsonify({'ok': False, 'error': 'missing_credential'}), 400

    try:
        claims = verify_google_id_token(
            credential, settings.google_oauth_client_id,
        )
    except Exception as exc:
        logger.warning('One Tap JWT verification failed: %s', exc)
        return jsonify({'ok': False, 'error': 'invalid_credential'}), 401

    sub = claims.get('sub')
    email = (claims.get('email') or '').lower().strip()
    email_verified = bool(claims.get('email_verified'))
    given_name = claims.get('given_name')
    family_name = claims.get('family_name')

    if not sub or not email:
        return jsonify({'ok': False, 'error': 'incomplete_claims'}), 400

    safe_claims = {
        k: claims.get(k) for k in
        ('sub', 'email', 'email_verified', 'given_name', 'family_name', 'locale')
        if claims.get(k) is not None
    }

    identity = AuthIdentity.find_by_provider_sub(
        AuthIdentity.PROVIDER_GOOGLE, sub,
    )

    if identity:
        user = identity.user
        if not user.is_active:
            return jsonify({'ok': False, 'error': 'inactive'}), 403
        identity.email = email
        identity.email_verified = email_verified
        identity.raw_claims = safe_claims
        identity.touch()
    else:
        if AuthIdentity.find_password_identity_by_email(email):
            return jsonify({
                'ok': False,
                'error': 'email_collision',
                'login_url': url_for('auth.login'),
            }), 409
        try:
            user = User.create_with_oauth(
                provider=AuthIdentity.PROVIDER_GOOGLE,
                sub=sub, email=email, email_verified=email_verified,
                first_name=given_name, last_name=family_name,
                raw_claims=safe_claims,
            )
            logger.info('One Tap created user id=%d email=%s', user.id, user.email)
        except Exception:
            db.session.rollback()
            logger.exception('One Tap: failed to create user')
            return jsonify({'ok': False, 'error': 'create_failed'}), 500

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('One Tap: db.commit failed')
        return jsonify({'ok': False, 'error': 'db_error'}), 500

    session.clear()
    login_user(user, remember=True)
    return jsonify({'ok': True, 'next': url_for('auth.account')})


# =============================================================
# Apple Sign In (Phase 5)
# =============================================================

@auth_bp.route('/apple/start', methods=['GET'])
def apple_start():
    """Початок Apple Sign In. Підтримує action=login (default) | link."""
    client = get_apple_client()
    if client is None:
        flash('Apple вхід наразі не налаштовано', 'error')
        return redirect(url_for('auth.login'))

    action = request.args.get('action', ACTION_LOGIN)
    if action == ACTION_LINK and not current_user.is_authenticated:
        return redirect(url_for('auth.login'))

    session[SESSION_OAUTH_ACTION] = action
    next_url = request.args.get('next', '')
    if _is_safe_redirect_url(next_url):
        session[SESSION_OAUTH_NEXT] = next_url
    else:
        session.pop(SESSION_OAUTH_NEXT, None)

    redirect_uri = url_for('auth.apple_callback', _external=True)
    return client.authorize_redirect(redirect_uri)


@auth_bp.route('/apple/callback', methods=['GET', 'POST'])
@csrf.exempt
def apple_callback():
    """Apple використовує response_mode=form_post -- callback приходить
    POST-ом з form-data (state, code, id_token, опційно 'user').

    GET-варіант підтримуємо лише для diagnostic-помилок Apple (вона
    інколи редіректить GET-ом при помилках). Authlib сам читає
    request.form.
    """
    client = get_apple_client()
    if client is None:
        flash('Apple вхід наразі не налаштовано', 'error')
        return redirect(url_for('auth.login'))

    try:
        token = client.authorize_access_token()
    except OAuthError as exc:
        logger.warning('Apple Sign In error: %s', exc.error)
        flash('Помилка автентифікації через Apple. Спробуйте ще раз.', 'error')
        return redirect(url_for('auth.login'))

    # OIDC claims (sub, email, email_verified, is_private_email).
    userinfo = token.get('userinfo') or {}
    sub = userinfo.get('sub')
    email = (userinfo.get('email') or '').lower().strip()
    # Apple's email_verified -- це JSON string "true"/"false" або bool.
    raw_verified = userinfo.get('email_verified')
    email_verified = bool(raw_verified) and str(raw_verified).lower() != 'false'
    is_private_email = bool(userinfo.get('is_private_email'))

    if not sub:
        logger.warning('Apple Sign In: missing sub in id_token: %s', userinfo)
        flash('Apple не повернув необхідні дані. Спробуйте ще раз.', 'error')
        return redirect(url_for('auth.login'))

    # 'user' приходить ЛИШЕ при першому логіні у формі (JSON-encoded).
    # Кешуємо у raw_claims -- інакше при повторному логіні цих даних
    # вже не буде.
    given_name = family_name = None
    user_field = request.form.get('user')
    if user_field:
        import json
        try:
            user_data = json.loads(user_field)
            name = user_data.get('name') or {}
            given_name = name.get('firstName')
            family_name = name.get('lastName')
        except (ValueError, AttributeError):
            logger.warning('Apple: failed to parse user field %r', user_field)

    safe_claims = {
        'sub': sub,
        'email': email or None,
        'email_verified': email_verified,
        'is_private_email': is_private_email,
        'given_name': given_name,
        'family_name': family_name,
    }
    safe_claims = {k: v for k, v in safe_claims.items() if v is not None}

    action = session.pop(SESSION_OAUTH_ACTION, ACTION_LOGIN)
    next_url = session.pop(SESSION_OAUTH_NEXT, None)

    if action == ACTION_LINK:
        return _handle_link(
            AuthIdentity.PROVIDER_APPLE,
            sub, email, email_verified, safe_claims, next_url,
        )
    return _handle_login(
        AuthIdentity.PROVIDER_APPLE,
        sub, email, email_verified, given_name, family_name,
        safe_claims, next_url,
    )


@auth_bp.route('/apple/unlink', methods=['POST'])
@login_required
def apple_unlink():
    return _unlink_provider(AuthIdentity.PROVIDER_APPLE)
