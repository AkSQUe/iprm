"""Реферальна програма: коди, посилання, атрибуція, нарахування балів.

Кожен учасник (User) і тренер (Trainer) має власний стабільний реферальний
код. Посилання з цим кодом розповсюджує реферер; параметр ``ref`` -- ключ
атрибуції (захоплюється при реєстрації), а UTM-мітки -- для аналітики GA4.

Фаза 1: генерація кодів і побудова посилань. Фаза 2: захоплення атрибуції
(cookie -> event_registrations.referral_code) і резолв реферера для адмінки.
Фаза 3: нарахування/анулювання бонусних балів (ReferralReward) при зміні
статусу оплати та баланс реферера.
"""
import logging
import re
import secrets
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.site_settings import SiteSettings

logger = logging.getLogger(__name__)

# Параметр атрибуції у посиланні (?ref=<code>).
REF_PARAM = 'ref'
# UTM-мітки для GA4 (source/medium сталі; campaign описує тип реферера).
UTM_SOURCE = 'referral'

# Cookie атрибуції: зберігає код реферера між візитом за посиланням і
# фактичною реєстрацією. Last-touch: кожен новий валідний ?ref= перезаписує.
REF_COOKIE = 'iprm_ref'
REF_COOKIE_MAX_AGE = 60 * 60 * 24 * 60  # 60 днів
# Дедуп кліків: код, який уже порахували в цій сесії (щоб рефреш не надував).
CLICK_COOKIE = 'iprm_refc'
CLICK_DEDUP_MAX_AGE = 60 * 60 * 24  # 1 доба
# Груба сигнатура ботів/краулерів у User-Agent (щоб не рахувати їхні кліки).
_BOT_RE = re.compile(
    r'bot|crawl|spider|slurp|bing|yandex|duckduck|baidu|'
    r'facebookexternalhit|whatsapp|telegrambot|viber|preview|scan|monitor',
    re.I,
)
# Форма коду: префікс u/t + 8 hex (див. _generate_code). Валідуємо перед тим,
# як приймати з недовіреного джерела (query/cookie).
_CODE_RE = re.compile(r'^[ut][0-9a-f]{8}$')


def is_valid_code(code):
    """Чи має рядок форму нашого реферального коду (u/t + 8 hex)."""
    return bool(code and _CODE_RE.match(code))


def _settings():
    """SiteSettings із кешу запиту (g.site_settings), інакше з БД.

    Уникає повторних запитів у hot-path (after_request на кожній відповіді)."""
    from flask import g, has_request_context
    if has_request_context():
        cached = getattr(g, 'site_settings', None)
        if cached is not None:
            return cached
    return SiteSettings.get()


def _generate_code(prefix):
    """Короткий URL-безпечний код: префікс + 8 hex-символів (alphanumeric)."""
    return f'{prefix}{secrets.token_hex(4)}'


def ensure_referral_code(obj, prefix):
    """Повернути (за потреби -- згенерувати й зберегти) referral_code для
    моделі з колонкою ``referral_code``. Робить flush, але не commit.

    Префікс (``u``/``t``) гарантує глобальну унікальність між User і Trainer.
    Колізії практично неможливі (4 млрд варіантів), але на випадок унікального
    індексу робимо кілька спроб.
    """
    if obj.referral_code:
        return obj.referral_code
    for _ in range(5):
        code = _generate_code(prefix)
        obj.referral_code = code
        db.session.add(obj)
        try:
            db.session.flush()
            return code
        except IntegrityError:
            db.session.rollback()
            db.session.add(obj)
            obj.referral_code = None
    # Вкрай малоймовірно: не вдалося підібрати унікальний код.
    raise RuntimeError('Не вдалося згенерувати унікальний реферальний код')


def _base_url():
    """Канонічна база сайту (як у email_service) без хвостового слеша."""
    return (_settings().website_url or '').rstrip('/')


def build_referral_url(code, target_url=None, campaign=UTM_SOURCE, medium='referral'):
    """Додати ref-код і UTM-мітки до цільового URL.

    target_url -- абсолютний або відносний шлях (напр. '/courses/prp').
    Порожній -> головна сторінка. Наявні query-параметри зберігаються;
    ref/utm_* перезаписуються нашими значеннями.
    """
    base = _base_url()
    if not target_url:
        target = base or '/'
    elif target_url.startswith(('http://', 'https://')):
        target = target_url
    elif base:
        target = base + '/' + target_url.lstrip('/')
    else:
        # Немає website_url -> посилання вийде без домену (непридатне для
        # розсилки). Лишаємо відносний шлях, але сигналізуємо адміну логом.
        logger.warning(
            'referral: website_url порожній -- реферальне посилання без домену'
        )
        target = target_url

    parts = urlparse(target)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[REF_PARAM] = code
    query['utm_source'] = UTM_SOURCE
    query['utm_medium'] = medium
    query['utm_campaign'] = campaign
    return urlunparse(parts._replace(query=urlencode(query)))


def qr_svg(url, border=4):
    """Самодостатній inline-SVG QR-коду посилання (чорні модулі на білому).

    На відміну від certificate_service.qr_svg (брендований градієнт під
    WeasyPrint), тут простий self-contained SVG для вставки у веб-сторінку.
    """
    import segno
    matrix = list(segno.make(url, error='m').matrix)
    n = len(matrix)
    size = n + 2 * border
    rects = []
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            if val:
                rects.append(f'<rect x="{c + border}" y="{r + border}" width="1" height="1"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'shape-rendering="crispEdges" role="img" '
        f'aria-label="QR-код реферального посилання">'
        f'<rect width="{size}" height="{size}" fill="#ffffff"/>'
        f'<g fill="#111111">{"".join(rects)}</g></svg>'
    )


def current_inviter_name(request, user=None):
    """Ім'я реферера для банера довіри на публічних сторінках (або None).

    Джерело коду: ?ref= -> серверний pending -> cookie. Не показуємо, якщо
    реферер = сам користувач або програму вимкнено.
    """
    try:
        if not _settings().referral_enabled:
            return None
    except Exception:
        return None
    code = request.args.get(REF_PARAM)
    if not is_valid_code(code):
        code = (getattr(user, 'pending_referral_code', None)
                if user is not None else None) or read_ref_cookie(request)
    if not is_valid_code(code):
        return None
    if user is not None and code == getattr(user, 'referral_code', None):
        return None
    referrer = resolve_referrer(code)
    return referrer['name'] if referrer else None


def user_referral_link(user, target_url=None):
    """Реферальне посилання учасника (генерує код за потреби)."""
    code = user.get_referral_code()
    return build_referral_url(code, target_url=target_url, medium='participant')


def trainer_referral_link(trainer, target_url=None):
    """Реферальне посилання тренера (генерує код за потреби)."""
    code = trainer.get_referral_code()
    return build_referral_url(code, target_url=target_url, medium='trainer')


# Підписаний токен self-service кабінету реферера (тренери без логіну).
_DASH_SALT = 'referral-dashboard'


def make_referrer_token(kind, referrer_id):
    """Підписаний токен для публічного кабінету реферера (kind:id)."""
    from itsdangerous import URLSafeSerializer
    from flask import current_app
    return URLSafeSerializer(current_app.secret_key, salt=_DASH_SALT).dumps(
        {'k': kind, 'i': referrer_id})


def load_referrer_token(token):
    """Розшифрувати токен -> (kind, id) або (None, None)."""
    from itsdangerous import URLSafeSerializer, BadData
    from flask import current_app
    try:
        data = URLSafeSerializer(current_app.secret_key, salt=_DASH_SALT).loads(token)
        kind, rid = data.get('k'), data.get('i')
        if kind in ('user', 'trainer') and isinstance(rid, int):
            return kind, rid
    except (BadData, AttributeError, Exception):
        pass
    return None, None


# ---- Захоплення атрибуції (Фаза 2) ----

def capture_referral_visit(request, response, user=None):
    """Єдиний обробник ref-візиту для after_request: cookie + серверний
    pending + лічильник кліків -- з одним читанням SiteSettings і одним commit.

    Викликається на кожній відповіді; уся робота лише коли є валідний ?ref=
    і програму увімкнено (інакше -- дешевий вихід).
    """
    code = request.args.get(REF_PARAM)
    if not is_valid_code(code):
        return response
    try:
        settings = _settings()
    except Exception:
        logger.exception('referral: settings read failed (visit)')
        return response
    if not settings.referral_enabled:
        return response

    # 1. Cookie (лише response, без БД).
    _set_ref_cookie(request, response, code, settings)

    # 2. Серверний pending для залогіненого (мутація без commit).
    pending_changed = False
    if user is not None and getattr(user, 'is_authenticated', False):
        pending_changed = _mutate_pending(user, code, settings)

    # 3. Клік -- лише GET-сторінки (не редіректи/статика/POST/боти) і не
    # повторний рефреш того самого коду в межах доби (dedup-cookie).
    is_page = (
        request.method == 'GET'
        and 'text/html' in (response.content_type or '')
        and response.status_code == 200
        and not _looks_like_bot(request)
        and request.cookies.get(CLICK_COOKIE) != code
    )

    try:
        if is_page:
            _increment_click(code)
        if pending_changed or is_page:
            db.session.commit()
        if is_page:
            response.set_cookie(
                CLICK_COOKIE, code, max_age=CLICK_DEDUP_MAX_AGE,
                httponly=True, samesite='Lax', secure=bool(request.is_secure), path='/',
            )
    except IntegrityError:
        db.session.rollback()
        if is_page:
            try:
                _increment_click(code, update_only=True)
                db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception:
        db.session.rollback()
        logger.exception('referral: visit persist failed')
    return response


def _looks_like_bot(request):
    """Груба евристика: краулер/бот за User-Agent (або порожній UA)."""
    ua = request.headers.get('User-Agent', '')
    if not ua:
        return True
    return bool(_BOT_RE.search(ua))


def _mutate_pending(user, code, settings):
    """Виставити user.pending_referral_code без commit. True якщо змінено."""
    if code == user.referral_code:
        return False
    current = user.pending_referral_code
    if current == code:
        return False
    if settings.referral_attribution == 'first' and is_valid_code(current):
        return False
    user.pending_referral_code = code
    return True


def _increment_click(code, update_only=False):
    """Інкремент денного лічильника кліків без commit (мутація сесії)."""
    from app.models.referral_click import ReferralClick
    from app.models.mixins import utcnow
    today = utcnow().date()
    updated = db.session.query(ReferralClick).filter_by(
        referral_code=code, day=today,
    ).update({ReferralClick.count: ReferralClick.count + 1})
    if not updated and not update_only:
        db.session.add(ReferralClick(referral_code=code, day=today, count=1))


def _set_ref_cookie(request, response, code, settings):
    """Виставити cookie атрибуції на response (з урахуванням first/last)."""
    existing = request.cookies.get(REF_COOKIE)
    if settings.referral_attribution == 'first' and is_valid_code(existing):
        return
    if existing == code:
        return
    max_age = int(settings.referral_cookie_days or 60) * 86400
    response.set_cookie(
        REF_COOKIE, code, max_age=max_age,
        httponly=True, samesite='Lax', secure=bool(request.is_secure), path='/',
    )


def capture_ref_cookie(request, response):
    """Сумісність: лише cookie-частина ref-візиту (для наявних викликів/тестів)."""
    code = request.args.get(REF_PARAM)
    if not is_valid_code(code):
        return response
    try:
        settings = _settings()
    except Exception:
        return response
    if settings.referral_enabled:
        _set_ref_cookie(request, response, code, settings)
    return response


def read_ref_cookie(request):
    """Повернути валідний код реферера з cookie (або None)."""
    code = request.cookies.get(REF_COOKIE)
    return code if is_valid_code(code) else None


def persist_pending_for_user(request, user):
    """Серверна атрибуція: зафіксувати ?ref= на залогіненому користувачі.

    Переживає втрату cookie/зміну пристрою. Поважає модель атрибуції
    (first/last) і не приймає власний код користувача. Комітить лише при зміні.
    """
    code = request.args.get(REF_PARAM)
    if not is_valid_code(code):
        return
    try:
        settings = _settings()
        if not settings.referral_enabled:
            return
    except Exception:
        logger.exception('referral: settings read failed (pending attribution)')
        return
    if not _mutate_pending(user, code, settings):
        return
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('referral: failed to persist pending code for user=%s', user.id)


def read_pending_ref(request, user):
    """Код реферера для атрибуції: спершу серверний (pending_referral_code),
    інакше cookie. Не очищує -- очищення робить caller після використання."""
    code = getattr(user, 'pending_referral_code', None)
    if is_valid_code(code):
        return code
    return read_ref_cookie(request)


def record_click(code):
    """Інкрементувати денний лічильник кліків по реф-коду (best-effort).

    Атомарний UPDATE; якщо рядка на сьогодні ще нема -- INSERT (гонка ->
    повторний UPDATE). Не кидає винятків.
    """
    if not is_valid_code(code):
        return
    try:
        _increment_click(code)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        try:
            _increment_click(code, update_only=True)
            db.session.commit()
        except Exception:
            db.session.rollback()
    except Exception:
        db.session.rollback()
        logger.exception('referral: failed to record click for %s', code)


def get_clicks_for_referrer(kind, referrer_id):
    """Сумарна кількість кліків по посиланню реферера."""
    from app.models.referral_click import ReferralClick
    from app.models.user import User
    from app.models.trainer import Trainer
    from sqlalchemy import func as _func
    obj = (db.session.get(User, referrer_id) if kind == 'user'
           else db.session.get(Trainer, referrer_id))
    code = getattr(obj, 'referral_code', None)
    if not code:
        return 0
    total = db.session.query(
        _func.coalesce(_func.sum(ReferralClick.count), 0)
    ).filter(ReferralClick.referral_code == code).scalar()
    return int(total or 0)


def get_clicks_by_code(codes):
    """Мапа {code: sum(clicks)} для набору кодів (bulk, для списків)."""
    from app.models.referral_click import ReferralClick
    from sqlalchemy import func as _func
    valid = [c for c in codes if is_valid_code(c)]
    if not valid:
        return {}
    rows = db.session.query(
        ReferralClick.referral_code, _func.sum(ReferralClick.count),
    ).filter(ReferralClick.referral_code.in_(valid)).group_by(
        ReferralClick.referral_code).all()
    return {code: int(total or 0) for code, total in rows}


def resolve_referrer(code):
    """Резолв коду у реферера. Повертає dict {kind, id, name, code} або None.

    kind -- 'user' | 'trainer'. Використовується для показу "хто кого привів"
    і для нарахування балів. Тонка обгортка над resolve_referrers_bulk.
    """
    return resolve_referrers_bulk([code]).get(code)


def resolve_referrers_bulk(codes):
    """Резолв набору кодів у dict {code: {kind, id, name, code}}.

    Один запит на User-и і один на Trainer-и (уникаємо N+1 у списках адмінки).
    Невідомі/невалідні коди відсутні у результаті.
    """
    from app.models.user import User
    from app.models.trainer import Trainer
    valid = {c for c in codes if is_valid_code(c)}
    if not valid:
        return {}
    user_codes = [c for c in valid if c.startswith('u')]
    trainer_codes = [c for c in valid if c.startswith('t')]
    out = {}
    if user_codes:
        for u in User.query.filter(User.referral_code.in_(user_codes)).all():
            out[u.referral_code] = {
                'kind': 'user', 'id': u.id,
                'name': u.full_name or u.email, 'code': u.referral_code,
            }
    if trainer_codes:
        for t in Trainer.query.filter(Trainer.referral_code.in_(trainer_codes)).all():
            out[t.referral_code] = {
                'kind': 'trainer', 'id': t.id,
                'name': t.full_name, 'code': t.referral_code,
            }
    return out


# ---- Нарахування балів (Фаза 3) ----

def _referrer_contact(kind, referrer_id):
    """Email + ім'я реферера для сповіщення (або (None, None))."""
    if kind == 'user':
        from app.models.user import User
        u = db.session.get(User, referrer_id)
        return (u.email, (u.full_name or u.email)) if u else (None, None)
    from app.models.trainer import Trainer
    t = db.session.get(Trainer, referrer_id)
    return (t.email, t.full_name) if t else (None, None)


def _compute_maturity(settings):
    """(status, matures_at) для нового нарахування за налаштуваннями."""
    days = int(settings.referral_maturity_days or 0)
    if days <= 0:
        return 'granted', None
    from datetime import timedelta
    from app.models.mixins import utcnow
    return 'pending', utcnow() + timedelta(days=days)


def _active_reward_count(kind, referrer_id):
    """Кількість активних (granted+pending) нарахувань реферера -- для стелі."""
    from app.models.referral_reward import ReferralReward
    return ReferralReward.query.filter(
        ReferralReward.referrer_kind == kind,
        ReferralReward.referrer_id == referrer_id,
        ReferralReward.status.in_(('granted', 'pending')),
    ).count()


def _is_self_referral(referrer, reg):
    """Антифрод: реферер = сам покупець (за id або за email)."""
    buyer = reg.user
    buyer_email = (buyer.email or '').strip().lower() if buyer else ''
    if referrer['kind'] == 'user' and referrer['id'] == reg.user_id:
        return True
    ref_email, _ = _referrer_contact(referrer['kind'], referrer['id'])
    ref_email = (ref_email or '').strip().lower()
    return bool(buyer_email and ref_email and buyer_email == ref_email)


def _notify_referrer_award(reg, kind, referrer_id, points):
    """Best-effort лист рефереру про нарахування. Не кидає винятків."""
    try:
        if not _settings().referral_notify_referrer:
            return
        email, name = _referrer_contact(kind, referrer_id)
        if not email:
            return
        event_title = None
        if reg.instance and reg.instance.course:
            event_title = reg.instance.course.title
        from app.services.email_service import EmailService
        EmailService.send_referral_award(
            to_email=email, referrer_name=name, points=points,
            balance=get_balance(kind, referrer_id), event_title=event_title,
            idempotency_key=f'referral-award-{reg.id}',
        )
    except Exception:
        logger.exception('Failed to notify referrer for reg=%s', reg.id)


def award_for_paid_registration(reg):
    """Нарахувати бонусні бали рефереру за оплачену реєстрацію.

    Ідемпотентно (UNIQUE registration_id): повторний виклик -> no-op. Best-effort,
    самостійно комітить. Повертає ReferralReward або None (нічого не нараховано).

    Умови нарахування:
      - програму увімкнено (referral_enabled);
      - реєстрація має referral_code, який резолвиться у реального реферера;
      - реєстрація реально платна (payment_amount > 0) і оплачена;
      - реферер != сам учасник (антифрод);
      - ставка referral_points_per_paid > 0.
    """
    from app.models.referral_reward import ReferralReward

    code = getattr(reg, 'referral_code', None)
    if not is_valid_code(code):
        return None
    # Платна й оплачена (безкоштовні події не нараховують).
    if reg.payment_status != 'paid':
        return None
    if not reg.payment_amount or float(reg.payment_amount) <= 0:
        return None

    settings = _settings()
    if not settings.referral_enabled:
        return None
    points = int(settings.referral_points_per_paid or 0)
    if points <= 0:
        return None

    referrer = resolve_referrer(code)
    if not referrer:
        return None
    # Антифрод: не нараховуємо самому собі (за id або email).
    if _is_self_referral(referrer, reg):
        return None

    status, matures_at = _compute_maturity(settings)

    # Ідемпотентність: одне нарахування на реєстрацію (UNIQUE registration_id).
    existing = ReferralReward.query.filter_by(registration_id=reg.id).first()
    if existing is not None:
        # Повторна оплата після повернення -> реактивуємо анульований рядок
        # (за поточною ставкою), а не лишаємо реферера без балів.
        if existing.status == 'voided':
            existing.status = status
            existing.matures_at = matures_at
            existing.voided_at = None
            existing.notes = None
            existing.points = points
            existing.referrer_kind = referrer['kind']
            existing.referrer_id = referrer['id']
            existing.referral_code = code
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.exception('Failed to reactivate referral reward reg=%s', reg.id)
                return None
            logger.info('Referral reward reactivated: reg=%s %s:%s +%dp (%s)',
                        reg.id, referrer['kind'], referrer['id'], points, status)
            _refresh_balance(referrer['kind'], referrer['id'])
            if status == 'granted':
                _notify_referrer_award(reg, referrer['kind'], referrer['id'], points)
        return existing

    # Стеля нарахувань на реферера (0 -- без ліміту).
    cap = int(settings.referral_max_per_referrer or 0)
    if cap > 0 and _active_reward_count(referrer['kind'], referrer['id']) >= cap:
        logger.info('Referral cap reached for %s:%s (cap=%d) -- skip reg=%s',
                    referrer['kind'], referrer['id'], cap, reg.id)
        return None

    reward = ReferralReward(
        registration_id=reg.id,
        referrer_kind=referrer['kind'],
        referrer_id=referrer['id'],
        referral_code=code,
        points=points,
        status=status,
        matures_at=matures_at,
    )
    db.session.add(reward)
    try:
        db.session.commit()
    except IntegrityError:
        # Гонка: інший потік уже створив нарахування -> повертаємо наявне.
        db.session.rollback()
        return ReferralReward.query.filter_by(registration_id=reg.id).first()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to grant referral reward for reg=%s', reg.id)
        return None
    logger.info('Referral reward granted: reg=%s %s:%s +%dp (%s)',
                reg.id, referrer['kind'], referrer['id'], points, status)
    if status == 'granted':
        _refresh_balance(referrer['kind'], referrer['id'])
    # Лист лише коли бали одразу активні; для pending -- при дозріванні.
    if status == 'granted':
        _notify_referrer_award(reg, referrer['kind'], referrer['id'], points)
    return reward


def mature_referral_rewards():
    """Активувати дозрілі pending-нарахування (matures_at <= now).

    Викликається scheduler-джобою. Кожне активоване -> лист рефереру.
    Повертає кількість активованих. Комітить порціями.
    """
    from app.models.referral_reward import ReferralReward
    from app.models.mixins import utcnow
    due = ReferralReward.query.filter(
        ReferralReward.status == 'pending',
        ReferralReward.matures_at.isnot(None),
        ReferralReward.matures_at <= utcnow(),
    ).all()
    if not due:
        return 0

    # Батч: один UPDATE статусу замість commit-на-рядок.
    ids = [r.id for r in due]
    try:
        db.session.query(ReferralReward).filter(
            ReferralReward.id.in_(ids)
        ).update({ReferralReward.status: 'granted'}, synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to mature referral rewards batch')
        return 0

    # Баланс -- по разу на реферера; листи -- по кожному нарахуванню.
    for kind, rid in {(r.referrer_kind, r.referrer_id) for r in due}:
        _refresh_balance(kind, rid)
    for reward in due:
        reg = reward.registration
        if reg is not None:
            _notify_referrer_award(reg, reward.referrer_kind,
                                   reward.referrer_id, reward.points)
    logger.info('Referral rewards matured: %d', len(due))
    return len(due)


def void_for_registration(reg, reason='Повернення коштів'):
    """Анулювати активне нарахування за реєстрацією (повернення/скасування).

    Ідемпотентно, best-effort, самостійно комітить. Не гейтиться
    referral_enabled -- анулювати треба навіть якщо програму вимкнули.
    """
    from app.models.referral_reward import ReferralReward
    reward = ReferralReward.query.filter(
        ReferralReward.registration_id == reg.id,
        ReferralReward.status.in_(('granted', 'pending')),
    ).first()
    if reward is None:
        return None
    kind, referrer_id = reward.referrer_kind, reward.referrer_id
    reward.void(reason=reason)
    try:
        db.session.commit()
        logger.info('Referral reward voided: reg=%s reason=%s', reg.id, reason)
    except Exception:
        db.session.rollback()
        logger.exception('Failed to void referral reward for reg=%s', reg.id)
        return None
    _refresh_balance(kind, referrer_id)
    return reward


def sync_reward_for_registration(reg):
    """Привести нарахування у відповідність до поточного статусу оплати.

    Викликається post-commit з усіх точок зміни статусу оплати:
      - 'paid'                -> award (з реактивацією анульованого);
      - 'refunded' / 'unpaid' -> void наявного (продаж скасовано);
      - 'pending'             -> не чіпаємо (транзитний статус).
    Ідемпотентно, безпечно викликати багаторазово.
    """
    if reg.payment_status == 'paid':
        return award_for_paid_registration(reg)
    if reg.payment_status in ('refunded', 'unpaid'):
        return void_for_registration(reg, reason='Оплату повернено/скасовано')
    return None


def _referrer_obj(kind, referrer_id):
    from app.models.user import User
    from app.models.trainer import Trainer
    return db.session.get(User if kind == 'user' else Trainer, referrer_id)


def recompute_balance(kind, referrer_id):
    """Авторитетний перерахунок балансу: SUM(granted rewards) + SUM(adjustments).

    Pending (недозрілі) і voided не враховуються. Використовується для
    оновлення денормалізованої колонки й для звірки.
    """
    from app.models.referral_reward import ReferralReward
    from app.models.referral_adjustment import ReferralAdjustment
    from sqlalchemy import func as _func
    rewards = db.session.query(
        _func.coalesce(_func.sum(ReferralReward.points), 0)
    ).filter(
        ReferralReward.referrer_kind == kind,
        ReferralReward.referrer_id == referrer_id,
        ReferralReward.status == 'granted',
    ).scalar()
    adj = db.session.query(
        _func.coalesce(_func.sum(ReferralAdjustment.points), 0)
    ).filter(
        ReferralAdjustment.referrer_kind == kind,
        ReferralAdjustment.referrer_id == referrer_id,
    ).scalar()
    return int(rewards or 0) + int(adj or 0)


def _refresh_balance(kind, referrer_id):
    """Перерахувати й зберегти денормалізований баланс реферера. Комітить.

    Викликається після кожної мутації, що впливає на баланс (award/void/
    mature/adjust). Best-effort -- не кидає винятків.
    """
    try:
        value = recompute_balance(kind, referrer_id)
        obj = _referrer_obj(kind, referrer_id)
        if obj is not None and (obj.referral_balance or 0) != value:
            obj.referral_balance = value
            db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('referral: failed to refresh balance %s:%s', kind, referrer_id)


def get_balance(kind, referrer_id):
    """Баланс реферера -- швидке читання денормалізованої колонки."""
    obj = _referrer_obj(kind, referrer_id)
    return int(getattr(obj, 'referral_balance', 0) or 0) if obj else 0


def get_pending_balance(kind, referrer_id):
    """Сума недозрілих (pending) балів реферера."""
    from app.models.referral_reward import ReferralReward
    from sqlalchemy import func as _func
    total = db.session.query(
        _func.coalesce(_func.sum(ReferralReward.points), 0)
    ).filter(
        ReferralReward.referrer_kind == kind,
        ReferralReward.referrer_id == referrer_id,
        ReferralReward.status == 'pending',
    ).scalar()
    return int(total or 0)


def add_adjustment(kind, referrer_id, points, reason, created_by_id=None):
    """Ручна корекція балансу реферера (+/-). Комітить. Повертає запис."""
    from app.models.referral_adjustment import ReferralAdjustment
    adj = ReferralAdjustment(
        referrer_kind=kind, referrer_id=referrer_id,
        points=int(points), reason=reason, created_by_id=created_by_id,
    )
    db.session.add(adj)
    db.session.commit()
    logger.info('Referral adjustment: %s:%s %+dp by=%s', kind, referrer_id,
                int(points), created_by_id)
    _refresh_balance(kind, referrer_id)
    return adj


def list_adjustments(kind, referrer_id):
    """Ручні корекції реферера (найновіші перші)."""
    from app.models.referral_adjustment import ReferralAdjustment
    return ReferralAdjustment.query.filter_by(
        referrer_kind=kind, referrer_id=referrer_id,
    ).order_by(ReferralAdjustment.created_at.desc()).all()


def fraud_flags(min_clicks=20):
    """Реферери з підозрілими патернами (для перевірки оператором).

    Сигнали: (1) багато повернень (voided >= active); (2) трафік без
    конверсій (кліків >= min_clicks, 0 активних нарахувань). Повертає список
    dict {kind, id, name, clicks, active, voided, reasons}.
    """
    from app.models.referral_reward import ReferralReward
    from app.models.referral_click import ReferralClick
    from sqlalchemy import func as _func, case

    reward_rows = db.session.query(
        ReferralReward.referrer_kind, ReferralReward.referrer_id,
        ReferralReward.referral_code,
        _func.sum(case((ReferralReward.status.in_(('granted', 'pending')), 1), else_=0)).label('active'),
        _func.sum(case((ReferralReward.status == 'voided', 1), else_=0)).label('voided'),
    ).group_by(
        ReferralReward.referrer_kind, ReferralReward.referrer_id,
        ReferralReward.referral_code,
    ).all()

    reward_codes = [r.referral_code for r in reward_rows]
    clicks_map = get_clicks_by_code(reward_codes)
    name_map = resolve_referrers_bulk(reward_codes)
    flags = []
    for r in reward_rows:
        active, voided = int(r.active or 0), int(r.voided or 0)
        clicks = clicks_map.get(r.referral_code, 0)
        reasons = []
        if voided and voided >= max(1, active):
            reasons.append(f'Багато повернень: {voided} анульовано / {active} активних')
        if clicks >= min_clicks and active == 0:
            reasons.append(f'Трафік без конверсій: {clicks} кліків, 0 активних')
        if reasons:
            info = name_map.get(r.referral_code)
            flags.append({
                'kind': r.referrer_kind, 'id': r.referrer_id,
                'name': info['name'] if info else r.referral_code,
                'clicks': clicks, 'active': active, 'voided': voided,
                'reasons': reasons,
            })

    # Коди з великим трафіком, але БЕЗ жодного нарахування.
    reward_set = set(reward_codes)
    click_rows = db.session.query(
        ReferralClick.referral_code, _func.sum(ReferralClick.count).label('c'),
    ).group_by(ReferralClick.referral_code).having(
        _func.sum(ReferralClick.count) >= min_clicks).all()
    lonely = [c for c, _ in click_rows if c not in reward_set]
    lonely_names = resolve_referrers_bulk(lonely)
    click_by_code = {c: int(total or 0) for c, total in click_rows}
    for code in lonely:
        info = lonely_names.get(code)
        if not info:
            continue
        flags.append({
            'kind': info['kind'], 'id': info['id'], 'name': info['name'],
            'clicks': click_by_code.get(code, 0), 'active': 0, 'voided': 0,
            'reasons': [f'Трафік без конверсій: {click_by_code.get(code, 0)} кліків, 0 нарахувань'],
        })
    flags.sort(key=lambda f: f['clicks'], reverse=True)
    return flags


def list_referrer_rewards(kind, referrer_id, limit=50):
    """Нарахування реферера (найновіші перші) з підвантаженими курсом/заходом.

    Для кабінету учасника й адмін-деталізації реферера.
    """
    from app.models.referral_reward import ReferralReward
    from app.models.registration import EventRegistration
    from app.models.course_instance import CourseInstance
    from sqlalchemy.orm import joinedload
    query = ReferralReward.query.options(
        joinedload(ReferralReward.registration)
        .joinedload(EventRegistration.instance)
        .joinedload(CourseInstance.course),
    ).filter(
        ReferralReward.referrer_kind == kind,
        ReferralReward.referrer_id == referrer_id,
    ).order_by(ReferralReward.created_at.desc())
    if limit:
        query = query.limit(limit)
    return query.all()
