"""Сторінка повернення коштів -- спільна для обох типів замовлень.

Окрема сторінка, а не діалог `data-confirm` на кнопці: повернення тепер
має суму й підставу, а їх треба ввести й побачити перед проведенням.
Діалог браузера цього не вміє, а повернути не ту суму -- це або недоплата
учаснику, або віддані гроші, які за політикою мали лишитись у нас.

Одна сторінка на обидва типи замовлень, бо форма й перевірки однакові:
різниця лише в тому, який `initiate_*_refund` викликати наприкінці.
"""
import logging

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db, limiter
from app.models.online_enrollment import OnlineEnrollment
from app.models.registration import EventRegistration
from app.models.refund_request import RefundRequest
from app.services import refund_policy, refund_requests
from app.services.liqpay import get_liqpay_service
from app.services.payment_ops import PaymentOps

logger = logging.getLogger(__name__)


def _safe_next(default_endpoint):
    """Куди повернути адміна після проведення.

    Приймаємо лише відносний шлях свого сайту: `next` приходить із
    посилання в списку, і відкритий редирект тут дав би зовнішній сайт у
    адмінці за один клік.
    """
    target = request.values.get('next', '')
    # Другий символ перевіряємо окремо: `/\evil.test` починається з одного
    # слеша, але браузери трактують `/\` як протокол-відносний URL -- і це
    # знову відкритий редирект, лише записаний інакше.
    if target.startswith('/') and target[1:2] not in ('/', '\\'):
        return target
    return url_for(default_endpoint)


def _linked_request(kind, order):
    """Заявка, з якої адмін прийшов на цю сторінку (?request=<id>).

    Звіряємо не лише id, а й належність замовленню: інакше підмінений
    параметр закрив би чужу заявку разом із цим поверненням.
    """
    raw = request.values.get('request')
    if not raw or not raw.isdigit():
        return None
    item = db.session.get(RefundRequest, int(raw))
    if item is None or not item.is_open:
        return None
    owner_id = item.enrollment_id if kind == 'enrollment' else item.registration_id
    return item if owner_id == order.id else None


def _load(kind, order_id):
    """Замовлення + куди повертатись + людська назва типу."""
    if kind == 'enrollment':
        order = db.session.get(OnlineEnrollment, order_id)
        return order, 'admin.online_orders_list'
    order = db.session.get(EventRegistration, order_id)
    return order, 'admin.liqpay'


@admin_bp.route('/refunds/<any(registration, enrollment):kind>/<int:order_id>',
                methods=['GET', 'POST'])
@admin_required
@limiter.limit('30 per hour', methods=['POST'])
def refund_form(kind, order_id):
    order, back_endpoint = _load(kind, order_id)
    if order is None:
        abort(404)

    back_url = _safe_next(back_endpoint)
    quote = refund_policy.quote_for(order)
    refund_req = _linked_request(kind, order)

    # Політика рахує відсоток від ПОВНОЇ вартості замовлення, а повернути
    # можна не більше залишку. Після першого часткового повернення ці два
    # числа розходяться, і у форму має підставитись менше з них.
    #
    # Якщо прийшли із заявки -- беремо ЇЇ знімок, а не свіжий розрахунок:
    # §4.2 прив'язує відсоток до дати подання, і поки заявка лежала в
    # черзі, сходинка встигла б зсунутись не на користь учасника.
    basis = refund_req.quoted_amount if refund_req is not None else quote.amount
    suggested = min(basis, order.refund_remaining)

    if request.method == 'GET':
        return render_template(
            'admin/refund_form.html',
            kind=kind, order=order, quote=quote, back_url=back_url,
            suggested=suggested, refund_req=refund_req,
        )

    if order.payment_status != 'paid':
        flash('Повернення можливе тільки для оплачених замовлень', 'error')
        return redirect(back_url)

    # Введене адміном зберігати нема куди -- після редиректу форма
    # підставить рекомендацію за політикою наново. Полів два, і надійність
    # тут важить більше, ніж збережений ввід.

    # Порожнє поле суми означає «весь залишок»: сервіс сам його порахує.
    amount = (request.form.get('amount') or '').strip() or None
    reason = (request.form.get('reason') or '').strip() or None
    force = request.form.get('force') == 'on'

    # Скільки вже було повернуто ДО операції: різниця дасть суму саме цього
    # повернення, яку інакше нізвідки взяти -- сервіс віддає лише (ok, текст).
    refunded_before = order.refunded_total

    ops = PaymentOps(get_liqpay_service())
    if kind == 'enrollment':
        ok, message = ops.initiate_enrollment_refund(
            order, current_user, amount=amount, reason=reason, force=force,
        )
    else:
        ok, message = ops.initiate_refund(
            order, current_user, amount=amount, reason=reason,
        )

    if ok and refund_req is not None:
        # Заявку закриваємо ПІСЛЯ успішного повернення й окремим комітом:
        # гроші вже пішли, і збій на цьому кроці має лишити заявку
        # відкритою (видно й можна закрити вручну), а не відкотити оплату.
        try:
            refund_requests.mark_approved(
                refund_req, current_user,
                refunded_amount=order.refunded_total - refunded_before,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Refund done but request #%s left open', refund_req.id)

    flash(message, 'success' if ok else 'error')
    if ok:
        return redirect(back_url)

    # Помилка -- назад на форму, а не рендер на місці: невдале повернення
    # вже відкотило сесію (`_fail`), і малювати сторінку з протухлих
    # об'єктів означає впасти з 500 замість того, щоб показати причину.
    return redirect(url_for(
        'admin.refund_form', kind=kind, order_id=order_id, next=back_url,
        request=refund_req.id if refund_req is not None else None,
    ))
