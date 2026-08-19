"""Заявка на повернення коштів з особистого кабінету.

Політика §6.1 досі відсилає людину на пошту й телефон, а §6.2 перелічує
шість пунктів, які має містити звернення. На практиці це означає, що
частина заявок приходить без суми, без номера замовлення й без причини, і
розбір починається з листування.

Форма закриває це тим, що знає сама: хто подає, за яке замовлення, скільки
сплачено й скільки належить за політикою. У людини лишається одне поле,
якого система вигадати не може, -- причина.
"""
import logging

from flask import render_template, redirect, url_for, flash, request, abort
from flask_babel import gettext as _
from flask_login import login_required, current_user

from app.auth import auth_bp
from app.extensions import db, limiter
from app.models.online_enrollment import OnlineEnrollment
from app.models.registration import EventRegistration
from app.services import refund_policy, refund_requests

logger = logging.getLogger(__name__)


def _load_own_order(kind, order_id):
    """Замовлення поточного користувача або 404.

    Перевірка власника тут не формальність: `order_id` приходить з URL, і
    без неї сторінка показувала б чужі суми, а форма приймала б заявку на
    чуже замовлення.
    """
    model = OnlineEnrollment if kind == 'enrollment' else EventRegistration
    order = db.session.get(model, order_id)
    if order is None or order.user_id != current_user.id:
        abort(404)
    return order


@auth_bp.route('/account/refund/<any(registration, enrollment):kind>/<int:order_id>',
               methods=['GET', 'POST'])
@login_required
@limiter.limit('10 per hour', methods=['POST'])
def refund_request(kind, order_id):
    order = _load_own_order(kind, order_id)
    allowed, problem = refund_requests.can_request(order)

    if not allowed:
        flash(problem, 'error')
        return redirect(url_for('auth.account'))

    quote = refund_policy.quote_for(order)

    if request.method == 'GET':
        return render_template(
            'auth/refund_request.html', order=order, kind=kind, quote=quote,
        )

    item, problem = refund_requests.create(
        order, current_user,
        reason=request.form.get('reason'),
        payout_details=request.form.get('payout_details'),
    )

    if item is None:
        # Редирект, а не рендер на місці: збій запису вже відкотив сесію,
        # і малювати сторінку з протухлих ORM-об'єктів означає 500 замість
        # причини. Те саме рішення, що й на адмінській формі повернення.
        flash(problem, 'error')
        return redirect(url_for('auth.refund_request', kind=kind,
                                order_id=order.id))

    flash(_('Заявку прийнято. Ми розглянемо її протягом 3 робочих днів '
            'і надішлемо відповідь на вашу пошту.'), 'success')
    return redirect(url_for('auth.account'))
