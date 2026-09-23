from flask import Blueprint
from flask_login import current_user

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
def require_staff():
    """Другий шар поверх @permission_required: у адмінку заходить лише
    носій хоч однієї ролі. В'юха без декоратора (якби сторож вимкнули)
    все одно закрита для сторонніх. Відмова та сама, що й у декораторі
    (``deny``): JSON-запит отримує JSON-тіло, інакше fetch у
    admin-access-matrix.js трактував би редирект на логін як успіх."""
    from app.rbac.decorators import deny
    if not current_user.is_authenticated:
        return deny(anonymous=True)
    if not current_user.is_staff:
        return deny(anonymous=False)


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


@admin_bp.context_processor
def inject_pending_material_requests():
    """Лічильник неперевірених заявок на матеріали для сайдбара.

    `context_processor` блупринта, а не додатка -- з тієї ж причини, що й
    сусідній лічильник повернень: інакше COUNT їхав би на кожну публічну
    сторінку заради числа, видимого лише в адмінці.

    Fail-soft: сайдбар малюється на КОЖНІЙ адмін-сторінці, і збій цього
    запиту не має класти, скажімо, редагування курсу.
    """
    from app.extensions import db
    try:
        from app.services import material_request_service as mrq
        return {'pending_material_requests': mrq.pending_review_count()}
    except Exception:
        # Без відкату на Postgres транзакція лишається перерваною, і падає
        # уже решта рендера -- тобто вся адмінка, від якої фейлсофт мав
        # захистити.
        db.session.rollback()
        return {'pending_material_requests': 0}


from app.admin import routes  # noqa: F401,E402
