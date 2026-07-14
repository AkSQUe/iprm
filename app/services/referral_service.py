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
# Форма коду: префікс u/t + 8 hex (див. _generate_code). Валідуємо перед тим,
# як приймати з недовіреного джерела (query/cookie).
_CODE_RE = re.compile(r'^[ut][0-9a-f]{8}$')


def is_valid_code(code):
    """Чи має рядок форму нашого реферального коду (u/t + 8 hex)."""
    return bool(code and _CODE_RE.match(code))


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
    return (SiteSettings.get().website_url or '').rstrip('/')


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


def user_referral_link(user, target_url=None):
    """Реферальне посилання учасника (генерує код за потреби)."""
    code = user.get_referral_code()
    return build_referral_url(code, target_url=target_url, medium='participant')


def trainer_referral_link(trainer, target_url=None):
    """Реферальне посилання тренера (генерує код за потреби)."""
    code = trainer.get_referral_code()
    return build_referral_url(code, target_url=target_url, medium='trainer')


# ---- Захоплення атрибуції (Фаза 2) ----

def capture_ref_cookie(request, response):
    """Якщо у запиті є валідний ?ref=<code> і програму увімкнено -- записати
    його у cookie на response (last-touch). Викликається з after_request.

    SiteSettings читаємо лише коли параметр присутній (щоб не робити зайвий
    запит до БД на кожному response).
    """
    code = request.args.get(REF_PARAM)
    if not is_valid_code(code):
        return response
    try:
        if not SiteSettings.get().referral_enabled:
            return response
    except Exception:
        logger.exception('referral: failed to read settings for cookie capture')
        return response
    # Не перезаписуємо тим самим значенням (уникаємо зайвого Set-Cookie).
    if request.cookies.get(REF_COOKIE) == code:
        return response
    secure = bool(request.is_secure)
    response.set_cookie(
        REF_COOKIE, code,
        max_age=REF_COOKIE_MAX_AGE,
        httponly=True, samesite='Lax', secure=secure, path='/',
    )
    return response


def read_ref_cookie(request):
    """Повернути валідний код реферера з cookie (або None)."""
    code = request.cookies.get(REF_COOKIE)
    return code if is_valid_code(code) else None


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


def _notify_referrer_award(reg, kind, referrer_id, points):
    """Best-effort лист рефереру про нарахування. Не кидає винятків."""
    try:
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

    settings = SiteSettings.get()
    if not settings.referral_enabled:
        return None
    points = int(settings.referral_points_per_paid or 0)
    if points <= 0:
        return None

    referrer = resolve_referrer(code)
    if not referrer:
        return None
    # Антифрод: не нараховуємо самому собі.
    if referrer['kind'] == 'user' and referrer['id'] == reg.user_id:
        return None

    # Ідемпотентність: одне нарахування на реєстрацію (UNIQUE registration_id).
    existing = ReferralReward.query.filter_by(registration_id=reg.id).first()
    if existing is not None:
        # Повторна оплата після повернення -> реактивуємо анульований рядок
        # (за поточною ставкою), а не лишаємо реферера без балів.
        if existing.status == 'voided':
            existing.status = 'granted'
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
            logger.info('Referral reward reactivated: reg=%s %s:%s +%dp',
                        reg.id, referrer['kind'], referrer['id'], points)
            _notify_referrer_award(reg, referrer['kind'], referrer['id'], points)
        return existing

    reward = ReferralReward(
        registration_id=reg.id,
        referrer_kind=referrer['kind'],
        referrer_id=referrer['id'],
        referral_code=code,
        points=points,
        status='granted',
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
    logger.info('Referral reward granted: reg=%s %s:%s +%dp',
                reg.id, referrer['kind'], referrer['id'], points)
    _notify_referrer_award(reg, referrer['kind'], referrer['id'], points)
    return reward


def void_for_registration(reg, reason='Повернення коштів'):
    """Анулювати активне нарахування за реєстрацією (повернення/скасування).

    Ідемпотентно, best-effort, самостійно комітить. Не гейтиться
    referral_enabled -- анулювати треба навіть якщо програму вимкнули.
    """
    from app.models.referral_reward import ReferralReward
    reward = ReferralReward.query.filter_by(
        registration_id=reg.id, status='granted',
    ).first()
    if reward is None:
        return None
    reward.void(reason=reason)
    try:
        db.session.commit()
        logger.info('Referral reward voided: reg=%s reason=%s', reg.id, reason)
        return reward
    except Exception:
        db.session.rollback()
        logger.exception('Failed to void referral reward for reg=%s', reg.id)
        return None


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


def get_balance(kind, referrer_id):
    """Баланс реферера: SUM(points) активних (granted) нарахувань."""
    from app.models.referral_reward import ReferralReward
    from sqlalchemy import func as _func
    total = db.session.query(
        _func.coalesce(_func.sum(ReferralReward.points), 0)
    ).filter(
        ReferralReward.referrer_kind == kind,
        ReferralReward.referrer_id == referrer_id,
        ReferralReward.status == 'granted',
    ).scalar()
    return int(total or 0)


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
