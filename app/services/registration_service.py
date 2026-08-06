"""Registration business logic service (Course+CourseInstance era).

Реєстрація прив'язана до CourseInstance. `event_id` на таблиці
event_registrations зберігається як nullable artifact для legacy-рядків,
але не використовується новим кодом.
"""
import logging
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.services import promo_service

logger = logging.getLogger(__name__)


def assign_place_number(reg):
    """Призначити sequential place_number у межах CourseInstance.

    Викликається в момент 'paid'-транзишн (LiqPay callback) або одразу
    для безкоштовних подій. Номер: 1, 2, 3, ... per-instance.

    Атомарність: SELECT FOR UPDATE на CourseInstance-row серіалізує
    паралельні виклики на той самий курс. Якщо partial-unique-index
    впав на race -- caller отримає IntegrityError і має зробити retry.

    Idempotent: якщо place_number вже встановлено -- повертаємо
    наявний без перепризначення.
    """
    if reg.place_number is not None:
        return reg.place_number

    # Row-lock на CourseInstance: серіалізує паралельні assign на тому
    # самому instance. Інші instances не зачіпаються (нема contention).
    db.session.query(CourseInstance).filter_by(
        id=reg.instance_id
    ).with_for_update().one()

    max_n = db.session.query(
        func.coalesce(func.max(EventRegistration.place_number), 0)
    ).filter(
        EventRegistration.instance_id == reg.instance_id,
        EventRegistration.place_number.isnot(None),
    ).scalar() or 0

    reg.place_number = int(max_n) + 1
    logger.info(
        'Assigned place_number=%d to REG-%d (instance=%d)',
        reg.place_number, reg.id, reg.instance_id,
    )
    return reg.place_number


def find_existing(user_id, instance_id):
    """Знайти існуючу реєстрацію user+instance, або None."""
    return EventRegistration.query.filter_by(
        user_id=user_id, instance_id=instance_id,
    ).first()


def check_capacity(instance_id):
    """Перевірити наявність місць на instance з row-lock.

    Повертає (has_capacity: bool, locked_instance: CourseInstance | None).
    Caller повинен зробити commit або rollback.
    """
    locked_instance = (
        db.session.query(CourseInstance)
        .with_for_update()
        .filter_by(id=instance_id)
        .first()
    )
    if not locked_instance:
        return False, None

    cap = locked_instance.effective_max_participants
    if not cap:
        return True, locked_instance

    active_count = (
        db.session.query(func.count(EventRegistration.id))
        .filter(
            EventRegistration.instance_id == instance_id,
            EventRegistration.status.notin_(['cancelled']),
        )
        .scalar()
    )
    return active_count < cap, locked_instance


def create_or_reactivate(user_id, instance, form_data, existing=None, tariff=None,
                         referral_code=None, promo=None):
    """Створити або переактивувати реєстрацію на CourseInstance.

    Args:
        user_id: Current user ID.
        instance: CourseInstance model instance.
        form_data: Dict (phone, specialty, workplace, experience_years,
            license_number, payment_method). payment_method опціональний
            ('liqpay' за замовчуванням); для безкоштовних подій ігнорується.
        existing: Існуюча cancelled-реєстрація для реактивації, або None.
            Якщо не-cancelled -- ValueError (caller порушив інваріант).
        tariff: Обраний InstanceTariff (тарифна вилка) -- визначає
            payment_amount. Валідність (активний, доступний) перевіряє
            caller; належність до instance перевіряється тут.
        promo: Перевірений PromoCode (promo_service.validate) або None.
            Знижка застосовується до ціни тарифу/проведення; код на 100%
            робить реєстрацію безкоштовною з усіма наслідками (одразу
            confirmed/paid і номер місця).

    Returns:
        (registration, is_free) tuple. Caller мусить сам викликати
        db.session.commit() для персистенції -- сервіс лише мутує сесію
        для кращої композиції з іншими операціями (audit, email, webhook).
    """
    if existing is not None and existing.status != 'cancelled':
        raise ValueError(
            f'create_or_reactivate: existing registration status={existing.status!r} '
            'is not cancelled -- caller must check before passing existing.'
        )
    if tariff is not None and tariff.instance_id != instance.id:
        raise ValueError(
            f'create_or_reactivate: tariff #{tariff.id} belongs to instance '
            f'{tariff.instance_id}, not {instance.id}.'
        )

    base_price = Decimal(
        tariff.price if tariff is not None else (instance.effective_price or 0)
    )
    # Знижку рахує сам код (відсоток або сума), обрізаючи її сумою
    # замовлення -- 100% і "мінус 5000 грн" з ціни 3000 дають рівно нуль.
    discount = promo.discount_for(base_price) if promo is not None else Decimal(0)
    price = base_price - discount
    is_free = price == 0
    new_status = 'confirmed' if is_free else 'pending'
    new_payment = 'paid' if is_free else 'unpaid'
    # Безкоштовні події оплачуються одразу -- спосіб оплати не релевантний.
    payment_method = 'liqpay' if is_free else (
        form_data.get('payment_method') or 'liqpay'
    )
    if payment_method not in dict(EventRegistration.PAYMENT_METHODS):
        payment_method = 'liqpay'

    if existing is not None:
        existing.phone = form_data['phone']
        existing.specialty = form_data['specialty']
        existing.workplace = form_data['workplace']
        existing.experience_years = form_data.get('experience_years')
        existing.license_number = form_data.get('license_number')
        existing.payment_amount = price
        existing.payment_method = payment_method
        existing.tariff_id = tariff.id if tariff is not None else None
        existing.status = new_status
        existing.payment_status = new_payment
        existing.payment_id = None
        existing.paid_at = None
        reg = existing
    else:
        reg = EventRegistration(
            user_id=user_id,
            instance_id=instance.id,
            phone=form_data['phone'],
            specialty=form_data['specialty'],
            workplace=form_data['workplace'],
            experience_years=form_data.get('experience_years'),
            license_number=form_data.get('license_number'),
            payment_amount=price,
            payment_method=payment_method,
            tariff_id=tariff.id if tariff is not None else None,
            status=new_status,
            payment_status=new_payment,
            referral_code=referral_code or None,
        )
        db.session.add(reg)

    # Реферальна атрибуція: не перезаписуємо вже наявну (first-touch у межах
    # реєстрації), але заповнюємо реактивовану cancelled-реєстрацію, якщо код
    # раніше не був зафіксований.
    if referral_code and not reg.referral_code:
        reg.referral_code = referral_code

    # Промокод: списання у реєстр і лічильник -- лише коли реєстрація вже
    # має id. apply_to_registration сам виставляє payment_amount/знімок
    # знижки (те саме `price`, порахували вище для is_free).
    if promo is not None:
        db.session.flush()
        promo_service.apply_to_registration(promo, reg, base_price)
    elif reg.promo_code_id is not None or reg.discount_amount is not None:
        # Реактивація скасованої реєстрації без коду: старе списання має
        # звільнити місце у ліміті, інакше код лишається "витраченим".
        # discount_amount перевіряємо окремо -- знімок переживає видалення
        # коду (FK SET NULL) і без чистки спотворював би суму до знижки.
        promo_service.detach(reg, reason='Реєстрацію оформлено без промокоду')

    # Для безкоштовних подій -- одразу присвоюємо номер місця, бо немає
    # окремого 'paid'-транзишн (платіж не очікується). Робиться ДО commit
    # caller-ом; flush щоб reg отримав id.
    if is_free:
        db.session.flush()
        try:
            assign_place_number(reg)
        except Exception:
            logger.exception(
                'Failed to assign place_number for free REG-%d', reg.id,
            )
            # не критично -- адмін зможе виставити вручну

    return reg, is_free
