from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


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
