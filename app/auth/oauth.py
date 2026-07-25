"""OAuth/OIDC routes: Google (redirect + One Tap) і Apple Sign In.

Routes:
  GET  /auth/google/start      -- редірект на Google authorize endpoint
                                  (?action=link -- прив'язка до current_user)
  GET  /auth/google/callback   -- exchange code, lookup/link/create user
  POST /auth/google/onetap     -- credential JWT від Google One Tap (JSON)
  POST /auth/google/unlink     -- (логін потрібен) видалити Google identity
  GET  /auth/oauth/collision   -- пояснення "email уже зареєстровано"
  GET  /auth/apple/start, GET|POST /auth/apple/callback, POST /auth/apple/unlink

Мовного префікса роути не мають (localize=False): їхні URL зафіксовані в
консолях Google/Apple.

Вхід розв'язує спільний резолвер _resolve_oauth_login() -- три сценарії:
  1. Знайдено identity (provider, sub) -> логін.
  2. Не знайдено, але email уже належить наявному User -> прив'язуємо
     identity до нього, якщо володіння скринькою доведене з обох боків
     (див. _can_attach_to_existing); інакше -- сторінка-пояснення
     "цей email уже зареєстровано" (захист від pre-hijacking, OWASP).
  3. Інакше -- створюємо новий User через User.create_with_oauth().
     email_verified Google завжди true для @gmail.com, але перевіряємо
     claim явно (для Workspace доменів інколи буває false).

Link-flow:
  - Залогінений юзер на /auth/account/connections клікає "Прив'язати
    Google" -> GET /auth/google/start?action=link -> action осідає в сесії.
  - У callback при action=link: lookup identity (provider, sub). Якщо вже
    належить ІНШОМУ юзеру -> помилка. Інакше -- identity з
    user_id=current_user.id.
"""
import logging
import secrets

from authlib.integrations.base_client.errors import OAuthError
from flask import (
    flash, redirect, render_template, request, session, url_for,
)
from flask_babel import gettext as _
from flask_login import current_user, login_required, login_user
from sqlalchemy.exc import IntegrityError

from app.auth import auth_bp
from app.auth._helpers import is_safe_redirect_url
from app.extensions import db, csrf, limiter
from app.models.auth_identity import AuthIdentity
from app.models.user import User
from app.services.google_oauth import (
    GoogleKeysUnavailable, get_google_client, verify_google_id_token,
)
from app.services.apple_signin import get_apple_client

logger = logging.getLogger(__name__)

# Session keys
SESSION_OAUTH_NEXT = '_oauth_next'
SESSION_OAUTH_ACTION = '_oauth_action'   # 'login' (default) | 'link'
SESSION_OAUTH_COLLISION = '_oauth_collision'
SESSION_ONETAP_NONCE = '_onetap_nonce'

ACTION_LOGIN = 'login'
ACTION_LINK = 'link'

# Результати _resolve_oauth_login() -- спільні для redirect-flow і One Tap.
RESOLVE_OK = 'ok'              # вхід за наявною identity
RESOLVE_CREATED = 'created'    # створено новий акаунт
RESOLVE_LINKED = 'linked'      # identity прив'язано до наявного акаунта
RESOLVE_INACTIVE = 'inactive'
RESOLVE_COLLISION = 'collision'
RESOLVE_FAILED = 'failed'

# Статуси, за яких юзера можна логінити.
RESOLVE_SUCCESS = (RESOLVE_OK, RESOLVE_CREATED, RESOLVE_LINKED)


def _capture_ui_language(user):
    """Мова листів = мова інтерфейсу при OAuth-самореєстрації (uk = NULL)."""
    from flask_babel import get_locale
    ui_lang = str(get_locale() or '')
    if ui_lang and ui_lang != 'uk':
        user.preferred_language = ui_lang


@auth_bp.app_template_global('google_onetap_nonce')
def google_onetap_nonce():
    """Nonce для Google One Tap -- прив'язка credential до цієї сесії.

    Без нього endpoint приймав би будь-який валідний Google-credential,
    зокрема підсунутий зловмисником (login CSRF: жертву тихо логінять у
    чужий акаунт). Google кладе nonce у підписаний id_token, а ми
    звіряємо його з сесією.

    Один nonce на сесію (не на рендер), щоб кілька відкритих вкладок не
    інвалідували одна одну. Викликається лише з _google_onetap.html,
    тобто тільки коли віджет реально показуємо.
    """
    nonce = session.get(SESSION_ONETAP_NONCE)
    if not nonce:
        nonce = secrets.token_urlsafe(24)
        session[SESSION_ONETAP_NONCE] = nonce
    return nonce


@auth_bp.route('/google/start', methods=['GET'], localize=False)
def google_start():
    """Початок OAuth-flow. action=login (default) або action=link
    (за наявності query-string ?action=link І залогіненого юзера)."""
    client = get_google_client()
    if client is None:
        flash(_('Google вхід наразі не налаштовано'), 'error')
        return redirect(url_for('auth.login'))

    action = request.args.get('action', ACTION_LOGIN)
    if action == ACTION_LINK and not current_user.is_authenticated:
        # link-flow вимагає вже залогіненого юзера
        return redirect(url_for('auth.login'))

    # Збережемо action і next URL у сесії -- callback їх прочитає.
    session[SESSION_OAUTH_ACTION] = action
    next_url = request.args.get('next', '')
    if is_safe_redirect_url(next_url):
        session[SESSION_OAUTH_NEXT] = next_url
    else:
        session.pop(SESSION_OAUTH_NEXT, None)

    redirect_uri = url_for('auth.google_callback', _external=True)
    return client.authorize_redirect(redirect_uri)


@auth_bp.route('/google/callback', methods=['GET'], localize=False)
def google_callback():
    """Обробка повернення з Google. Витягуємо OIDC-claims через Authlib
    (валідація state/nonce/підпису -- автоматично). Далі -- три гілки:
    existing identity / email-collision / new user."""
    client = get_google_client()
    if client is None:
        flash(_('Google вхід наразі не налаштовано'), 'error')
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
        flash(_('Помилка автентифікації через Google. Спробуйте ще раз.'), 'error')
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
        flash(_('Google не повернув необхідні дані. Спробуйте ще раз.'), 'error')
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


def _can_attach_to_existing(user, provider_email_verified):
    """Чи безпечно прив'язати OAuth-identity до НАЯВНОГО акаунта з тим
    самим email -- без пароля і без окремого підтвердження від юзера.

    Так, якщо провайдер підтвердив володіння адресою І при цьому:
      - наш акаунт теж має підтверджений email (обидві сторони довели
        володіння тією самою скринькою -- це та сама людина), АБО
      - в акаунта взагалі немає пароля (захоплювати нічого; доказ
        володіння скринькою рівносильний нашому ж reset-password --
        саме так входять імпортовані учасники, у яких пароля не було).

    Ні, якщо пароль є, а email у нас НЕ підтверджений: такий акаунт міг
    завести зловмисник на чужу адресу, і пароль лишився б у нього
    (pre-hijacking; OWASP). Тут показуємо сторінку-пояснення.
    """
    if not provider_email_verified:
        return False
    if user.email_confirmed:
        return True
    has_password = AuthIdentity.query.filter(
        AuthIdentity.user_id == user.id,
        AuthIdentity.provider == AuthIdentity.PROVIDER_PASSWORD,
        AuthIdentity.password_hash.isnot(None),
    ).first() is not None
    return not has_password


def _resolve_oauth_login(provider, sub, email, email_verified,
                         given_name, family_name, safe_claims):
    """Знайти / прив'язати / створити User за OIDC-claims. НЕ комітить --
    caller вирішує, коли фіксувати транзакцію.

    Спільний резолвер для redirect-flow і One Tap: логіка входу однакова,
    різниться лише формат відповіді (HTTP-редірект vs JSON).

    Повертає (user, status), де status -- одна з RESOLVE_* констант;
    user is None для всіх статусів, окрім RESOLVE_SUCCESS.
    """
    label = PROVIDER_LABELS.get(provider, provider)
    identity = AuthIdentity.find_by_provider_sub(provider, sub)

    if identity:
        user = identity.user
        if not user.is_active:
            return None, RESOLVE_INACTIVE
        if email:
            identity.email = email
        identity.email_verified = email_verified
        identity.raw_claims = safe_claims
        identity.touch()
        return user, RESOLVE_OK

    # Identity немає. Дивимось, чи є вже User із цим email: у нас 1200+
    # імпортованих учасників без жодної identity, тож шукати саме
    # password-identity недостатньо -- інакше create_with_oauth() впав би
    # на UNIQUE(users.email).
    user = User.query.filter_by(email=email).first() if email else None

    if user is None:
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
            _capture_ui_language(user)
            logger.info('Created %s OAuth user email=%s', label, email)
            return user, RESOLVE_CREATED
        except IntegrityError:
            # Гонка: паралельний запит уже створив цей акаунт (One Tap уміє
            # дублювати виклики -- у логах бачили 4 POST за 12 секунд).
            # Відкочуємось і йдемо гілкою прив'язки до вже створеного User.
            db.session.rollback()
            user = User.query.filter_by(email=email).first()
            if user is None:
                logger.exception('Failed to create %s OAuth user', label)
                return None, RESOLVE_FAILED
            logger.info(
                'Race creating %s OAuth user %s -- attaching to existing id=%d',
                label, email, user.id,
            )
        except Exception:
            db.session.rollback()
            logger.exception('Failed to create %s OAuth user', label)
            return None, RESOLVE_FAILED

    if not user.is_active:
        return None, RESOLVE_INACTIVE

    if not _can_attach_to_existing(user, email_verified):
        return None, RESOLVE_COLLISION

    db.session.add(AuthIdentity(
        user_id=user.id,
        provider=provider,
        provider_sub=str(sub),
        email=email,
        email_verified=email_verified,
        raw_claims=safe_claims,
    ))
    # Провайдер щойно підтвердив володіння скринькою -- фіксуємо це і в нас,
    # щоб не смикати юзера листом підтвердження після входу через OAuth.
    if email_verified and not user.email_confirmed:
        user.email_confirmed = True
    try:
        # Flush тут, а не на commit-і: так гонку по UNIQUE(provider, sub)
        # видно всередині резолвера, де її ще можна розв'язати.
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        existing = AuthIdentity.find_by_provider_sub(provider, sub)
        if existing is None:
            logger.exception('Failed to link %s identity for %s', label, email)
            return None, RESOLVE_FAILED
        logger.info('Race linking %s identity -- reusing id=%d', label, existing.id)
        return existing.user, RESOLVE_OK
    logger.info('Linked %s identity to existing user id=%d', label, user.id)
    return user, RESOLVE_LINKED


def _collision_url(email, label):
    """Зберегти контекст email-колізії в сесії і повернути URL сторінки-
    пояснення. Саме через сесію, а не query-string -- щоб email не світився
    в URL, логах nginx і Referer."""
    session[SESSION_OAUTH_COLLISION] = {'email': email, 'provider': label}
    return url_for('auth.oauth_collision')


@auth_bp.route('/oauth/collision', methods=['GET'], localize=False)
def oauth_collision():
    """Сторінка "email уже зареєстровано" -- спільна для redirect-flow і
    One Tap. Контекст одноразовий (pop): прямий захід без нього -> логін."""
    ctx = session.pop(SESSION_OAUTH_COLLISION, None)
    if not ctx:
        return redirect(url_for('auth.login'))
    return render_template('auth/oauth_email_collision.html', **ctx)


def _handle_login(provider, sub, email, email_verified, given_name, family_name,
                  safe_claims, next_url):
    """Гілка login redirect-flow. Працює для будь-якого OAuth/OIDC-
    провайдера (Google, Apple, ...) -- різниця лише у назві провайдера
    та у текстах повідомлень."""
    label = PROVIDER_LABELS.get(provider, provider)
    user, status = _resolve_oauth_login(
        provider, sub, email, email_verified, given_name, family_name, safe_claims,
    )

    if status == RESOLVE_INACTIVE:
        flash(_('Обліковий запис деактивовано'), 'error')
        return redirect(url_for('auth.login'))
    if status == RESOLVE_COLLISION:
        return redirect(_collision_url(email, label))
    if status not in RESOLVE_SUCCESS:
        flash(_('Помилка при створенні облікового запису'), 'error')
        return redirect(url_for('auth.login'))

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to persist %s login', label)
        flash(_('Помилка входу через %(provider)s. Спробуйте ще раз.', provider=label), 'error')
        return redirect(url_for('auth.login'))

    session.clear()
    login_user(user, remember=True)
    if status in (RESOLVE_CREATED, RESOLVE_LINKED):
        # flash() пише в сесію -- лише ПІСЛЯ session.clear().
        flash(_('Вітаємо! Тепер ви можете входити через %(provider)s.', provider=label), 'success')
    if next_url and is_safe_redirect_url(next_url):
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
            flash(_('%(provider)s вже прив\'язано до вашого облікового запису', provider=label), 'info')
        else:
            flash(
                _('Цей %(provider)s-акаунт вже прив\'язано до іншого облікового '
                  'запису. Зв\'яжіться з підтримкою для допомоги.', provider=label),
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
        flash(_('%(provider)s успішно прив\'язано до вашого облікового запису', provider=label), 'success')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to link %s identity', label)
        flash(_('Помилка при прив\'язці %(provider)s', provider=label), 'error')

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
        flash(_('%(provider)s не прив\'язано', provider=label), 'info')
        return redirect(url_for('auth.connections'))

    total = AuthIdentity.query.filter_by(user_id=current_user.id).count()
    if total <= 1:
        flash(
            _('Не можна видалити останній спосіб входу. Спочатку встановіть '
              'пароль або прив\'яжіть інший провайдер.'),
            'error',
        )
        return redirect(url_for('auth.connections'))

    db.session.delete(identity)
    try:
        db.session.commit()
        flash(_('%(provider)s від\'єднано від вашого облікового запису', provider=label), 'success')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to unlink %s identity', label)
        flash(_('Помилка при від\'єднанні'), 'error')

    return redirect(url_for('auth.connections'))


@auth_bp.route('/google/unlink', methods=['POST'], localize=False)
@login_required
def google_unlink():
    return _unlink_provider(AuthIdentity.PROVIDER_GOOGLE)


# =============================================================
# Google One Tap (Phase 6)
# =============================================================

@auth_bp.route('/google/onetap', methods=['POST'], localize=False)
@csrf.exempt
@limiter.limit('20 per hour')
def google_onetap():
    """Прийом credential JWT від Google One Tap (GSI library).

    Стандартний CSRF-токен тут не працює (запит іде з GSI, а не з нашої
    форми), тому запит прив'язуємо до сесії через nonce: він генерується
    при рендері віджета, Google кладе його в підписаний id_token, а ми
    звіряємо. Без цього будь-який валідний Google-credential логінив би
    жертву в чужий акаунт (login CSRF).

    Логіка lookup-or-link-or-create -- той самий _resolve_oauth_login(),
    що й у redirect-flow, але без HTTP-redirect (повертаємо JSON, фронт
    сам редіректить). email-collision -> 409 + URL сторінки-пояснення.
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

    expected_nonce = session.get(SESSION_ONETAP_NONCE)
    if not expected_nonce:
        # Віджет рендериться разом із nonce, тож його відсутність означає
        # або втрачену сесію (заблоковані cookie), або сторонній запит.
        logger.warning('One Tap: no nonce in session')
        return jsonify({'ok': False, 'error': 'invalid_credential'}), 401

    try:
        claims = verify_google_id_token(
            credential, settings.google_oauth_client_id,
            expected_nonce=expected_nonce,
        )
    except GoogleKeysUnavailable:
        # Наш збій (не дістали ключі Google), а не поганий токен -- 503,
        # щоб не плутати діагностику і не показувати юзеру "невалідний вхід".
        logger.exception('One Tap: Google JWKS unavailable')
        return jsonify({'ok': False, 'error': 'keys_unavailable'}), 503
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

    user, status = _resolve_oauth_login(
        AuthIdentity.PROVIDER_GOOGLE, sub, email, email_verified,
        given_name, family_name, safe_claims,
    )

    if status == RESOLVE_INACTIVE:
        return jsonify({'ok': False, 'error': 'inactive'}), 403
    if status == RESOLVE_COLLISION:
        return jsonify({
            'ok': False,
            'error': 'email_collision',
            'next': _collision_url(email, PROVIDER_LABELS[AuthIdentity.PROVIDER_GOOGLE]),
        }), 409
    if status not in RESOLVE_SUCCESS:
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

@auth_bp.route('/apple/start', methods=['GET'], localize=False)
def apple_start():
    """Початок Apple Sign In. Підтримує action=login (default) | link."""
    client = get_apple_client()
    if client is None:
        flash(_('Apple вхід наразі не налаштовано'), 'error')
        return redirect(url_for('auth.login'))

    action = request.args.get('action', ACTION_LOGIN)
    if action == ACTION_LINK and not current_user.is_authenticated:
        return redirect(url_for('auth.login'))

    session[SESSION_OAUTH_ACTION] = action
    next_url = request.args.get('next', '')
    if is_safe_redirect_url(next_url):
        session[SESSION_OAUTH_NEXT] = next_url
    else:
        session.pop(SESSION_OAUTH_NEXT, None)

    redirect_uri = url_for('auth.apple_callback', _external=True)
    return client.authorize_redirect(redirect_uri)


@auth_bp.route('/apple/callback', methods=['GET', 'POST'], localize=False)
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
        flash(_('Apple вхід наразі не налаштовано'), 'error')
        return redirect(url_for('auth.login'))

    try:
        token = client.authorize_access_token()
    except OAuthError as exc:
        logger.warning('Apple Sign In error: %s', exc.error)
        flash(_('Помилка автентифікації через Apple. Спробуйте ще раз.'), 'error')
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
        flash(_('Apple не повернув необхідні дані. Спробуйте ще раз.'), 'error')
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


@auth_bp.route('/apple/unlink', methods=['POST'], localize=False)
@login_required
def apple_unlink():
    return _unlink_provider(AuthIdentity.PROVIDER_APPLE)
