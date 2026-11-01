"""Admin: каталог дизайн-системи.

Каталог показує компоненти ЖИВИМИ -- підключає ті самі CSS-файли, з яких
малюються справжні сторінки. Тому він ламається разом із компонентом, якщо
той зламали, і тёмна тема перевіряється сама собою.

Жив на публічному /design-system із noindex; переїхав в адмінку, бо це
інструмент розробки, а не сторінка сайту. Стара адреса лишилась редиректом.
"""
from decimal import Decimal

from flask import render_template

from app.admin import admin_bp
from app.rbac import permission_required


@admin_bp.route('/design-system')
@permission_required('design_system.view')
def design_system():
    return render_template('admin/design_system.html',
                           bank_transfer_demo=_bank_transfer_demo())


def _bank_transfer_demo():
    """Вигадані реквізити для живого показу partials/_bank_transfer.html.

    QR будується тим самим кодом, що на сторінках і в рахунку, тож
    вітрина ламається разом із ним.
    """
    from app.services.payment_qr import build_nbu_qr_payload
    from app.services.payment_transfer import TransferDetails

    purpose = 'Оплата згідно рахунку № REG-1234 від 31.10.2026 за Береза Олена'
    iban = 'UA' + '0' * 27
    amount = Decimal('2500')
    return TransferDetails(
        recipient='ТОВ «ІПРМ»', edrpou='12345678', bank='АТ «Банк»',
        iban=iban, amount=amount, purpose=purpose,
        qr_payload=build_nbu_qr_payload(
            recipient_name='ТОВ «ІПРМ»', iban=iban, amount=amount,
            purpose=purpose, recipient_code='12345678'),
    )
