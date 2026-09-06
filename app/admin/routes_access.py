"""Сторінка «Доступ»: матриця прав і ролі.

Рядки матриці приходять із реєстру (app/rbac/registry.py), стан
перемикачів -- із role_permissions. Збереження -- JSON API після кожного
кліку (admin-access-matrix.js). CRUD ролей -- серверні форми (Task 12).
"""
import logging

from flask import abort, jsonify, render_template, request
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.admin import admin_bp
from app.extensions import db
from app.models.rbac import Role, UserRole
from app.rbac import permission_required, registry, service
from app.rbac.service import AccessError

audit_logger = logging.getLogger('audit')


def _roles_ordered():
    return (Role.query.options(selectinload(Role.permissions))
            .order_by(Role.sort_order, Role.display_name).all())


def _role_count(role, total):
    return total if role.name == registry.SUPER_ADMIN else len(role.permissions)


@admin_bp.route('/access')
@permission_required('access.view')
def access():
    roles = _roles_ordered()
    total = len(registry.ALL_PERMISSION_NAMES)
    granted = {r.id: {p.name for p in r.permissions} for r in roles}
    counts = {r.id: _role_count(r, total) for r in roles}
    holders = dict(db.session.query(UserRole.role_id, func.count())
                   .group_by(UserRole.role_id))
    groups = []
    for key, label, modules in registry.grouped_modules():
        groups.append({
            'key': key, 'label': label,
            'total': sum(len(m.actions) for m in modules),
            'modules': [{
                'name': m.name, 'label': m.label,
                'permissions': [{'name': n, 'label': registry.action_label(n)}
                                for n in m.permission_names()],
            } for m in modules],
        })
    return render_template(
        'admin/access.html',
        roles=roles, granted=granted, counts=counts, total=total,
        holders=holders, groups=groups,
        super_admin=registry.SUPER_ADMIN,
        can_manage=current_user.has_permission('access.manage'),
    )


def _json_role():
    """Розбирає тіло запиту й дістає роль за role_id.

    Повертає `(role, data, error)`: при валідному запиті `error` -- None,
    інакше `role` -- None, а `error` -- готова пара (jsonify(...), статус)
    для негайного `return` із виклику. Так обидва API-маршрути завжди
    відповідають JSON, а не HTML-сторінкою помилки з global error handler,
    яку рендерить голий `abort()`.
    """
    data = request.get_json(silent=True) or {}
    role_id = data.get('role_id')
    if type(role_id) is not int:
        return None, data, (jsonify(error='role_id має бути цілим числом'), 400)
    role = db.session.get(Role, role_id)
    if role is None:
        return None, data, (jsonify(error='Роль не знайдено'), 404)
    return role, data, None


@admin_bp.route('/access/api/matrix', methods=['PUT'])
@permission_required('access.manage')
def access_matrix_toggle():
    role, data, error = _json_role()
    if error is not None:
        return error
    try:
        service.set_role_permission(
            role, str(data.get('permission', '')), bool(data.get('granted')), current_user)
        db.session.commit()
    except AccessError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, role_id=role.id,
                   role_count=_role_count(role, len(registry.ALL_PERMISSION_NAMES)))


@admin_bp.route('/access/api/matrix/bulk', methods=['POST'])
@permission_required('access.manage')
def access_matrix_bulk():
    role, data, error = _json_role()
    if error is not None:
        return error
    mode = data.get('mode')
    if mode not in ('all', 'none'):
        return jsonify(error='mode має бути all або none'), 400
    try:
        granted = service.set_module_permissions(
            role, str(data.get('module', '')), mode == 'all', current_user)
        db.session.commit()
    except AccessError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    return jsonify(ok=True, role_id=role.id, module=data.get('module'),
                   granted=granted,
                   role_count=_role_count(role, len(registry.ALL_PERMISSION_NAMES)))


# Заглушки CRUD ролей: повна реалізація в Task 12. Потрібні вже тут, бо
# шаблон матриці посилається на них.
@admin_bp.route('/access/roles/new', methods=['GET', 'POST'])
@permission_required('access.manage')
def access_role_new():
    abort(404)


@admin_bp.route('/access/roles/<int:role_id>/edit', methods=['GET', 'POST'])
@permission_required('access.manage')
def access_role_edit(role_id):
    abort(404)


@admin_bp.route('/access/roles/<int:role_id>/delete', methods=['POST'])
@permission_required('access.manage')
def access_role_delete(role_id):
    abort(404)


@admin_bp.route('/access/roles/<int:role_id>/reset', methods=['POST'])
@permission_required('access.manage')
def access_role_reset(role_id):
    abort(404)
