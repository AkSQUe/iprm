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
