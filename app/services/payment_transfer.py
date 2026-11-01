"""Реквізити для оплати переказом -- одні на сторінку, лист і рахунок.

Учасник, якому кажуть «сплатіть через банк», має бачити рівно те, що
надруковано в рахунку: отримувача, ЄДРПОУ, банк, IBAN, суму, призначення
(з номером REG-/ONL-) і той самий платіжний QR НБУ. За номером у
призначенні сайт mm-medic зіставляє переказ із реєстрацією одразу; без
нього лишається пошук за ПІБ і сумою, який часто віддає рядок людині.

Правило «некоректні реквізити -- без QR» тут одне на всіх: QR, який банк
відхилить або заповнить неправильно, гірший за його відсутність, а текст
реквізитів лишається чинним і без нього.
"""
import io
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.models.site_settings import SiteSettings
from app.services.payment_purpose import build_payment_purpose
from app.services.payment_qr import build_nbu_qr_payload, qr_svg_data_uri

logger = logging.getLogger(__name__)

#: Отримувач за замовчуванням -- той самий, що в шапці рахунка.
DEFAULT_RECIPIENT = 'ІПРМ'

#: Номер замовлення в призначенні (REG-/ONL-/SUR-<id>).
_ORDER_REF = re.compile(r'(?:REG|ONL|SUR)-\d+')


def payment_qr_payload(settings, amount, purpose) -> Optional[str]:
    """Платіжний URL НБУ для QR або None, якщо реквізити для QR не годяться.

    Некоректний IBAN чи ЄДРПОУ в налаштуваннях не має ламати ні рахунок,
    ні сторінку, ні лист: вони лишаються чинними й без QR.
    """
    try:
        return build_nbu_qr_payload(
            recipient_name=settings.company_full_name or DEFAULT_RECIPIENT,
            iban=settings.bank_iban,
            amount=amount,
            purpose=purpose,
            recipient_code=settings.edrpou,
        )
    except ValueError as exc:
        logger.warning('Payment QR skipped: %s', exc)
        return None


def qr_png_bytes(payload: str) -> bytes:
    """PNG QR-коду для листа.

    Лист отримує саме PNG, а не SVG: Gmail і частина Outlook SVG не
    показують узагалі. Параметри ті самі, що в SVG рахунка (ECC M, без
    Micro QR, тиха зона 4 модулі), масштаб -- під ~200 px у листі.
    """
    import segno

    out = io.BytesIO()
    segno.make(payload, error='m', micro=False).save(
        out, kind='png', scale=5, border=4, light='#fff')
    return out.getvalue()


@dataclass(frozen=True)
class TransferDetails:
    """Усе, що показується учаснику для оплати переказом."""

    recipient: str
    edrpou: str
    bank: str
    iban: str
    amount: Decimal
    purpose: str
    qr_payload: Optional[str]

    @property
    def qr_svg_data_uri(self) -> Optional[str]:
        """SVG для `<img>` на сторінці -- той самий, що в PDF-рахунку."""
        return qr_svg_data_uri(self.qr_payload) if self.qr_payload else None

    @property
    def purpose_parts(self):
        """(до, номер, після) -- щоб сторінка не розривала «REG-» і число
        по різних рядках. Без номера -- (призначення, '', '')."""
        found = _ORDER_REF.search(self.purpose)
        if not found:
            return self.purpose, '', ''
        return (self.purpose[:found.start()], found.group(0),
                self.purpose[found.end():])

    def qr_png(self) -> Optional[bytes]:
        return qr_png_bytes(self.qr_payload) if self.qr_payload else None


def transfer_details(order, *, amount=None, purpose=None) -> TransferDetails:
    """Реквізити переказу для реєстрації (REG-) чи онлайн-запису (ONL-).

    `amount` і `purpose` -- для платежу, що не збігається із замовленням
    (доплата різниці тарифу): за замовчуванням беруться `payment_amount`
    і призначення рахунка.
    """
    settings = SiteSettings.get()
    value = Decimal(order.payment_amount or 0) if amount is None else Decimal(amount)
    text = build_payment_purpose(order) if purpose is None else purpose
    return TransferDetails(
        recipient=settings.company_full_name or DEFAULT_RECIPIENT,
        edrpou=settings.edrpou or '',
        bank=settings.bank_name or '',
        iban=settings.bank_iban or '',
        amount=value,
        purpose=text,
        qr_payload=payment_qr_payload(settings, value, text),
    )


def transfer_offered(order) -> bool:
    """Чи пропонувати учаснику оплату переказом -- ОДНА умова на всі місця.

    Сторінка реєстрації, токен-оплата, оформлення онлайн-курсу й лист «Реєстрацію
    підтверджено» беруть її звідси. Поки кожне місце мало свою, токен-оплата
    й оформлення показували QR при `pending` -- коли LiqPay уже тримає гроші,
    тобто запрошували заплатити вдруге, -- і на скасованій реєстрації, де
    переказ ІПРМ відхилить, а гроші доведеться повертати вручну.

    Реєстрація (REG-) чи онлайн-запис (ONL-) не скасовані, оплата саме
    `unpaid` (не `pending`, не `paid`, не `refunded`), сума більша за нуль і
    оплату за рахунком увімкнено в налаштуваннях.
    """
    if getattr(order, 'status', None) == 'cancelled':
        return False
    if getattr(order, 'payment_status', None) != 'unpaid':
        return False
    amount = getattr(order, 'payment_amount', None)
    if not (amount and amount > 0):
        return False
    return bool(SiteSettings.enabled_payment_methods().invoice)


def bank_details_for(order) -> Optional[TransferDetails]:
    """Реквізити переказу замовлення або None, якщо переказ не пропонується."""
    return transfer_details(order) if transfer_offered(order) else None
