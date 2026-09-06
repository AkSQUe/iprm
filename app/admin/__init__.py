from flask import Blueprint, abort, flash, jsonify, redirect, url_for
from flask_login import current_user

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
def require_staff():
    """Другий шар поверх @permission_required: у адмінку заходить лише
    носій хоч однієї ролі. В'юха без декоратора (якби сторож вимкнули)
    все одно закрита для сторонніх.

    JSON-запит (fetch з admin-access-matrix.js тощо) отримує JSON-тіло
    замість редиректу/HTML-403 -- інакше `r.json()` на клієнті падає, і
    autosave-код мовчки трактує обірвану сесію як успіх (Task 14, п.6)."""
    from app.rbac.decorators import _wants_json
    if not current_user.is_authenticated:
        if _wants_json():
            return jsonify(error='unauthorized'), 401
        flash('Будь ласка, увійдіть для доступу до цієї сторінки.', 'info')
        return redirect(url_for('auth.login'))
    if not current_user.is_staff:
        if _wants_json():
            return jsonify(error='forbidden'), 403
        abort(403)


@admin_bp.after_request
def add_noindex_header(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@admin_bp.context_processor
def inject_pending_refund_requests():
    """Лічильник нових заявок на повернення для сайдбара.

    `context_processor` блупринта, а не додатка: інакше COUNT їхав би на
    КОЖНУ публічну сторінку заради числа, яке видно тільки в адмінці.

    Fail-soft: сайдбар малюється на кожній адмін-сторінці, і збій цього
    запиту не має класти, скажімо, редагування курсу.
    """
    try:
        from app.services import refund_requests
        return {'pending_refund_requests': refund_requests.pending_count()}
    except Exception:
        return {'pending_refund_requests': 0}


from app.admin import routes  # noqa: F401,E402
