"""RBAC адмін-панелі.

    from app.rbac import permission_required
    @admin_bp.route('/courses')
    @permission_required('courses.view')
    def courses_list(): ...

Шаблони: {% if can('courses.manage') %} ... {% endif %}
"""
from flask_login import current_user

from . import registry
from .decorators import permission_required
from .service import has_any, has_permission


def init_app(app):
    app.jinja_env.globals['can'] = lambda name: has_permission(current_user, name)
    app.jinja_env.globals['can_any'] = lambda *names: has_any(current_user, names)
    from .cli import rbac_group
    app.cli.add_command(rbac_group)


__all__ = ['registry', 'has_permission', 'has_any', 'permission_required', 'init_app']
