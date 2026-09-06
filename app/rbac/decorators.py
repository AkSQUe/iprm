"""@permission_required('module.action', ...) -- досить БУДЬ-ЯКОГО з прав.

Анонімного веде на логін (як колишній admin_required), автентифікованого
без права зупиняє 403; запит, що чекає JSON, отримує JSON-тіло. Ту саму
розвилку використовує запобіжник блупринта admin (``deny``), щоб текст і
поведінка не розходились у двох місцях.
Атрибут _rbac_permissions читає тест-сторож tests/test_rbac/test_guards.py.
"""
from functools import wraps

from flask import abort, flash, jsonify, redirect, request, url_for
from flask_login import current_user

from . import registry
from .service import has_any

LOGIN_MESSAGE = 'Будь ласка, увійдіть для доступу до цієї сторінки.'


def wants_json():
    """Запит із fetch/API: відповідати JSON, а не редиректом чи HTML-403."""
    if request.is_json or '/api/' in request.path:
        return True
    return request.accept_mimetypes.best == 'application/json'


def deny(anonymous):
    """Відмова у доступі: редирект на логін або 401 JSON для аноніма,
    403 (HTML через abort або JSON) для автентифікованого без права."""
    if anonymous:
        if wants_json():
            return jsonify(error='unauthorized'), 401
        flash(LOGIN_MESSAGE, 'info')
        return redirect(url_for('auth.login'))
    if wants_json():
        return jsonify(error='forbidden'), 403
    abort(403)


def permission_required(*names):
    if not names:
        raise ValueError('permission_required потребує хоч одне право')
    for name in names:
        registry.assert_known(name)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return deny(anonymous=True)
            if not has_any(current_user, names):
                return deny(anonymous=False)
            return view(*args, **kwargs)
        wrapper._rbac_permissions = tuple(names)
        return wrapper
    return decorator
