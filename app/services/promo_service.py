"""Промокоди: пошук, валідація, застосування та анулювання.

Єдине джерело правди для всіх точок входу -- публічний чекаут
(registration.routes), адмінська форма учасника (routes_participants) і
адмінка кодів (routes_promo_codes).

Контракт: функції МУТУЮТЬ сесію без commit -- caller відповідає за
commit/rollback (так само, як participant_service). Виняток -- явно
названі функції звітності, які лише читають.

Доменні помилки -- PromoError з текстом, придатним для показу
користувачу (у публічному флоу він потрапляє у flash/JSON як є), тому
тексти проходять через gettext: цей екран бачать і ru/en-відвідувачі.
"""
import logging
import secrets
from decimal import Decimal

from flask_babel import gettext as _
from sqlalchemy import func

from app.extensions import db
from app.models.promo_code import DISCOUNT_PERCENT, PromoCode, PromoRedemption
from app.models.registration import EventRegistration

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

MAX_CODE_LENGTH = 64

# Алфавіт згенерованих кодів: без 0/O та 1/I/L -- код диктують телефоном і
# переписують з листа, тож схожі символи коштують дорожче за ентропію.
CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
GENERATED_SUFFIX_LENGTH = 6
# Скільки кодів дозволяємо згенерувати за раз (одна фарм-кампанія).
MAX_BATCH = 200

# Префікс кодів-подяк (видаються автоматично в листі про оплату). За ним
# їх видно в адмінському списку серед кодів, заведених руками.
THANKYOU_PREFIX = 'NEXT'


class PromoError(Exception):
    """Промокод не можна застосувати. Текст показуємо користувачу."""


def _actor():
    """Хто виконує дію -- для audit-логу.

    Знижка це гроші, тож слід має бути і від менеджера, і від публічного
    чекауту. Поза request-контекстом (scheduler, CLI) -- 'system'.
    """
    try:
        from flask_login import current_user
        if current_user and current_user.is_authenticated:
            return current_user.email
        return 'public'
    except Exception:
        return 'system'


def normalize_code(raw):
    """Канонічна форма коду для пошуку та унікальності.

    casefold (а не lower) -- бо коди кирилицею ("Дмитро") і регістр там
    поводиться не так прямолінійно, як у латиниці. Внутрішні пробіли
    прибираємо: людина, яка копіює код із листа, часто тягне їх за собою.
    """
    if not raw:
        return ''
    return ''.join(str(raw).split()).casefold()[:MAX_CODE_LENGTH]


def find(raw_code):
    """Знайти код за будь-яким написанням. None, якщо такого немає."""
    norm = normalize_code(raw_code)
    if not norm:
        return None
    return PromoCode.query.filter_by(code_norm=norm).first()


def generate_code(prefix='', attempts=20):
    """Згенерувати вільний код виду PREFIX-A7K3XY (або A7K3XY без префікса).

    Перевіряє зайнятість у БД (запит тягне за собою autoflush, тож коди,
    додані в цій же транзакції, теж видно -- це важливо для пакета).
    """
    prefix = ''.join((prefix or '').split()).strip('-')
    # Лишаємо місце під дефіс і суфікс, щоб не впертись у ліміт колонки.
    prefix = prefix[:MAX_CODE_LENGTH - GENERATED_SUFFIX_LENGTH - 1]
    for _ in range(attempts):
        suffix = ''.join(
            secrets.choice(CODE_ALPHABET) for _ in range(GENERATED_SUFFIX_LENGTH)
        )
        code = f'{prefix}-{suffix}' if prefix else suffix
        if find(code) is None:
            return code
    raise PromoError(_('Не вдалося згенерувати вільний код. Спробуйте інший префікс.'))


def generate_batch(count, prefix='', **fields):
    """Створити пакет одноразових кодів зі спільними налаштуваннями.

    Кейс фарми: замість одного коду на N використань кожен лікар отримує
    свій -- видно, хто саме скористався, і скасувати можна поштучно.
    Мутує сесію без commit; повертає список PromoCode.
    """
    count = max(1, min(int(count or 1), MAX_BATCH))
    codes = []
    for _ in range(count):
        code = generate_code(prefix)
        promo = PromoCode(code=code, code_norm=normalize_code(code), **fields)
        db.session.add(promo)
        codes.append(promo)
    audit_logger.info(
        'promo_batch_created prefix="%s" count=%s actor=%s',
        prefix, len(codes), _actor(),
    )
    return codes


# ===================== валідація =====================

def _check_scope(promo, instance):
    """Чи діє код на це проведення."""
    if promo.instance_id is not None and (
            instance is None or instance.id != promo.instance_id):
        raise PromoError(_('Цей промокод діє на інший захід'))
    if promo.course_id is not None and (
            instance is None or instance.course_id != promo.course_id):
        raise PromoError(_('Цей промокод діє на інший курс'))


def validate(raw_code, instance=None, amount=None, user_id=None):
    """Перевірити код і повернути (promo, discount, final).

    amount -- сума до знижки (ціна тарифу або проведення). Якщо не вказана,
    розрахунок пропускаємо і повертаємо (promo, None, None): корисно для
    адмінки, де сума ще не відома.

    user_id -- якщо відомий, одразу перевіряємо ліміт "на одну людину".
    У гостьовому чекауті користувач з'являється пізніше, тому там
    викликається окремо assert_user_limit().
    """
    promo = find(raw_code)
    if promo is None:
        raise PromoError(_('Промокод не знайдено'))
    if not promo.is_active:
        raise PromoError(_('Промокод вимкнено'))
    if promo.is_not_started:
        raise PromoError(_('Промокод ще не діє'))
    if promo.is_expired:
        raise PromoError(_('Термін дії промокоду минув'))
    if promo.is_exhausted:
        raise PromoError(_('Промокод вичерпано'))
    _check_scope(promo, instance)

    if user_id is not None:
        assert_user_limit(promo, user_id)

    if amount is None:
        return promo, None, None

    base = Decimal(amount or 0)
    if base <= 0:
        raise PromoError(_('Участь і так безкоштовна — промокод не потрібен'))

    discount = promo.discount_for(base)
    return promo, discount, base - discount


def assert_user_limit(promo, user_id, ignore_registration_id=None):
    """Перевірити ліміт застосувань коду однією людиною.

    ignore_registration_id -- не рахувати застосування цієї реєстрації
    (потрібно при редагуванні: людина повторно зберігає ту саму форму).
    """
    if promo.per_user_limit is None or user_id is None:
        return
    q = db.session.query(func.count(PromoRedemption.id)).filter(
        PromoRedemption.promo_code_id == promo.id,
        PromoRedemption.user_id == user_id,
        PromoRedemption.status == 'applied',
    )
    if ignore_registration_id is not None:
        q = q.filter(PromoRedemption.registration_id != ignore_registration_id)
    if (q.scalar() or 0) >= promo.per_user_limit:
        raise PromoError(_('Ви вже використали цей промокод'))


# ===================== застосування =====================

def apply_to_registration(promo, reg, original_amount):
    """Застосувати код до реєстрації: сума, знімок знижки, реєстр, лічильник.

    reg має бути вже у сесії з призначеним id (робимо flush за потреби).
    Повертає PromoRedemption. Не комітить.

    Повторне застосування ТОГО САМОГО коду (менеджер ще раз зберіг форму)
    оновлює наявний рядок -- лічильник не рухається, історія не засмічується.
    Інший код спершу анулює попередній: інакше в реєстрі лишилася б сума,
    якої ніхто не платив.
    """
    if reg.id is None:
        db.session.flush()

    base = Decimal(original_amount or 0)
    discount = promo.discount_for(base)
    final = base - discount

    current = _active_redemption(reg.id)
    if current is not None and current.promo_code_id == promo.id:
        current.original_amount = base
        current.discount_amount = discount
        current.final_amount = final
        reg.discount_amount = discount
        reg.payment_amount = final
        return current

    if current is not None:
        _void(current, 'Замінено іншим промокодом')
        reg.promo_code_id = None
        reg.discount_amount = None
        # Явний flush: інакше INSERT нового рядка міг би піти в БД раніше
        # за UPDATE старого (порядок операцій у межах flush визначає
        # SQLAlchemy), і partial-unique index на активне списання впав би.
        db.session.flush()

    # Row-lock серіалізує паралельні застосування того самого коду: без
    # нього два одночасні чекаути на код з max_uses=1 обидва пройшли б
    # перевірку і обидва отримали б знижку.
    locked = (
        db.session.query(PromoCode)
        .filter_by(id=promo.id)
        .with_for_update()
        .one()
    )
    if locked.is_exhausted:
        raise PromoError(_('Промокод вичерпано'))

    locked.used_count = (locked.used_count or 0) + 1

    redemption = PromoRedemption(
        promo_code_id=locked.id,
        registration_id=reg.id,
        user_id=reg.user_id,
        original_amount=base,
        discount_amount=discount,
        final_amount=final,
    )
    db.session.add(redemption)

    reg.promo_code_id = locked.id
    reg.discount_amount = discount
    reg.payment_amount = final

    logger.info(
        'Promo %s applied to REG-%s: %s -> %s (-%s)',
        locked.code, reg.id, base, final, discount,
    )
    audit_logger.info(
        'promo_applied code="%s" reg=%s user=%s amount=%s discount=%s final=%s '
        'used=%s actor=%s',
        locked.code, reg.id, reg.user_id, base, discount, final,
        locked.used_count, _actor(),
    )
    return redemption


def detach(reg, reason='Промокод знято'):
    """Зняти активне списання з реєстрації (лічильник повертається).

    Знімок discount_amount на реєстрації теж чистимо: сума, яку caller
    виставить далі, вже не має знижки. Не комітить.
    """
    redemption = _active_redemption(reg.id)
    if redemption is None:
        reg.promo_code_id = None
        reg.discount_amount = None
        return None
    _void(redemption, reason)
    reg.promo_code_id = None
    reg.discount_amount = None
    return redemption


def void_for_registration(reg, reason='Повернення коштів'):
    """Анулювати списання, але лишити знімок знижки на реєстрації.

    Використовується при поверненні коштів/скасуванні: місце у ліміті
    звільняється (код можна видати комусь іншому), а історія того, що
    людина платила зі знижкою, лишається у звітах.
    """
    redemption = _active_redemption(reg.id)
    if redemption is None:
        return None
    _void(redemption, reason)
    return redemption


def _active_redemption(registration_id):
    if registration_id is None:
        return None
    return PromoRedemption.query.filter_by(
        registration_id=registration_id, status='applied',
    ).first()


def _void(redemption, reason):
    redemption.void(reason)
    promo = (
        db.session.query(PromoCode)
        .filter_by(id=redemption.promo_code_id)
        .with_for_update()
        .first()
    )
    if promo is not None:
        # max(0, ...) -- захист від розсинхрону денормалізованого лічильника
        # (ручні правки в БД, історичні рядки); реєстр усе одно головніший.
        promo.used_count = max(0, (promo.used_count or 0) - 1)
    logger.info(
        'Promo redemption #%s voided (reg=%s): %s',
        redemption.id, redemption.registration_id, reason,
    )
    audit_logger.info(
        'promo_voided code="%s" reg=%s discount=%s reason="%s" actor=%s',
        promo.code if promo is not None else redemption.promo_code_id,
        redemption.registration_id, redemption.discount_amount,
        reason, _actor(),
    )


def sync_for_registration(reg):
    """Привести списання у відповідність зі станом реєстрації.

    Викликається після зміни платіжного статусу (payment_ops): повернення
    коштів або скасування звільняють використання коду. Не комітить --
    caller у payment_ops робить commit сам.
    """
    if reg.payment_status == 'refunded':
        return void_for_registration(reg, reason='Повернення коштів')
    if reg.status == 'cancelled':
        return void_for_registration(reg, reason='Реєстрацію скасовано')
    return None


# ===================== звітність =====================

def recount(promo):
    """Перерахувати used_count з реєстру (джерело правди). Не комітить."""
    actual = db.session.query(func.count(PromoRedemption.id)).filter(
        PromoRedemption.promo_code_id == promo.id,
        PromoRedemption.status == 'applied',
    ).scalar() or 0
    if promo.used_count != actual:
        logger.info(
            'Promo %s used_count drift: %s -> %s',
            promo.code, promo.used_count, actual,
        )
        promo.used_count = actual
    return actual


def stats(promo):
    """Агрегати для картки коду: застосування, знижка, оплачені.

    'discount_total' -- скільки грн віддано знижками за активними
    списаннями; 'paid_count' -- скільки з них дійшли до оплаченої
    (або безкоштовної підтвердженої) реєстрації.
    """
    # Один прохід по реєстру: лічильники обох статусів і сума знижок
    # беруться з тієї самої вибірки, замість трьох окремих COUNT-ів.
    by_status = dict(
        (status, (count, total)) for status, count, total in db.session.query(
            PromoRedemption.status,
            func.count(PromoRedemption.id),
            func.coalesce(func.sum(PromoRedemption.discount_amount), 0),
        ).filter(
            PromoRedemption.promo_code_id == promo.id,
        ).group_by(PromoRedemption.status).all()
    )
    applied, discount_total = by_status.get('applied', (0, 0))
    voided = by_status.get('voided', (0, 0))[0]

    paid = db.session.query(func.count(PromoRedemption.id)).select_from(
        PromoRedemption
    ).join(
        EventRegistration,
        EventRegistration.id == PromoRedemption.registration_id,
    ).filter(
        PromoRedemption.promo_code_id == promo.id,
        PromoRedemption.status == 'applied',
        EventRegistration.payment_status == 'paid',
    ).scalar() or 0

    return {
        'applied': applied,
        'discount_total': discount_total,
        'paid_count': paid,
        'voided': voided,
    }


# ===================== промокод-подяка =====================

def issue_thankyou_code(registration):
    """Персональний код на НАСТУПНИЙ курс для щойно оплаченої реєстрації.

    Навіщо: лист про оплату сам по собі -- глухий кут. Код зі строком дії
    дає причину повернутись на сайт, поки враження від покупки свіже.

    Код одноразовий (max_uses=1, per_user_limit=1) і діє на будь-який курс:
    сенс саме в тому, щоб людина пішла обирати наступний.

    Ідемпотентно: повторний виклик для тієї ж реєстрації (ретрай листа,
    ручна переcилка) повертає вже виданий код. МУТУЄ сесію без commit --
    як і решта функцій модуля.

    Повертає PromoCode або None, якщо механіку вимкнено чи налаштовано
    беззмістовно (0%, 0 днів).
    """
    from datetime import timedelta
    from app.models.mixins import utcnow
    from app.models.site_settings import SiteSettings

    if registration is None or not registration.id:
        return None

    existing = (
        PromoCode.query
        .filter_by(issued_for_registration_id=registration.id)
        .order_by(PromoCode.id.desc())
        .first()
    )
    if existing is not None:
        # Вичерпаний/протермінований код не перевидаємо: людина вже
        # скористалась пропозицією або пропустила її.
        return existing

    settings = SiteSettings.get()
    if not settings.thankyou_promo_enabled:
        return None

    percent = int(settings.thankyou_promo_percent or 0)
    days = int(settings.thankyou_promo_days or 0)
    if percent < 1 or percent > 100 or days < 1:
        logger.warning(
            'thankyou promo misconfigured: percent=%s days=%s -- код не видано',
            percent, days,
        )
        return None

    try:
        code = generate_code(THANKYOU_PREFIX)
    except PromoError:
        logger.exception('thankyou promo: не вдалося згенерувати код')
        return None

    promo = PromoCode(
        code=code,
        code_norm=normalize_code(code),
        description=f'Подяка за оплату REG-{registration.id}',
        discount_type=DISCOUNT_PERCENT,
        discount_value=Decimal(percent),
        max_uses=1,
        per_user_limit=1,
        valid_until=utcnow() + timedelta(days=days),
        issued_for_registration_id=registration.id,
        is_active=True,
    )
    db.session.add(promo)
    audit_logger.info(
        'promo_thankyou_issued code=%s percent=%s days=%s reg=%s',
        code, percent, days, registration.id,
    )
    return promo


def list_redemptions(promo, limit=200):
    """Історія застосувань коду (нові зверху) з учасником і заходом."""
    from sqlalchemy.orm import joinedload
    return (
        PromoRedemption.query
        .options(
            joinedload(PromoRedemption.user),
            joinedload(PromoRedemption.registration)
            .joinedload(EventRegistration.instance),
        )
        .filter_by(promo_code_id=promo.id)
        .order_by(PromoRedemption.created_at.desc())
        .limit(limit)
        .all()
    )
