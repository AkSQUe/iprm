"""Призначення платежу в рахунку ІПРМ.

Один рядок на PDF, XLSX, веб-реквізити й платіжний QR. Номер замовлення
(REG-<id> або ONL-<id>) у ньому -- контракт: за ним сайт mm-medic зіставляє
банківські надходження з реєстраціями. Суфікс «за <ПІБ учасника>» стоїть
завжди, коли ім'я відоме: платить часто не сам учасник, а клініка чи колега.

Перекладу немає свідомо: це банківські дані, а не підпис в інтерфейсі. Рядок
потрапляє в QR, і залежність від локалі давала б різні QR одного рахунку.
"""
from app.models.mixins import utcnow
from app.utils import KYIV, ensure_utc

_PREFIX = 'Оплата згідно рахунку №'


def order_ref(order) -> str:
    """REG-<id> для реєстрації, ONL-<id> для запису на онлайн-курс."""
    if hasattr(order, 'online_course_id'):
        return order.order_id
    return f'REG-{order.id}'


def build_payment_purpose(order) -> str:
    """«Оплата згідно рахунку № REG-1 від 31.10.2026 за Прізвище Ім'я По-батькові»."""
    created = ensure_utc(getattr(order, 'created_at', None)) or utcnow()
    purpose = (
        f'{_PREFIX} {order_ref(order)} '
        f'від {created.astimezone(KYIV).strftime("%d.%m.%Y")}'
    )
    user = getattr(order, 'user', None)
    name = ((user.full_name if user else '') or '').strip()
    if name:
        purpose = f'{purpose} за {name}'
    return purpose


def build_surcharge_purpose(transfer) -> str:
    """«Доплата різниці тарифу SUR-7 за Прізвище Ім'я По-батькові».

    Номер -- той самий order_id SUR-<id перенесення>, що й у LiqPay. Для
    mm-medic він означає «не зіставляти автоматично»: доплата -- окремий
    платіж, а сума різниці може випадково дорівнювати ціні іншої реєстрації
    тієї ж людини, і правило «ПІБ + сума» підтвердило б не те. Без номера
    саме так і сталося б.
    """
    purpose = f'Доплата різниці тарифу SUR-{transfer.id}'
    reg = getattr(transfer, 'registration', None)
    user = getattr(reg, 'user', None)
    name = ((user.full_name if user else '') or '').strip()
    if name:
        purpose = f'{purpose} за {name}'
    return purpose
