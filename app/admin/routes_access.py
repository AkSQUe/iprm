"""Сторінка «Доступ»: матриця прав і ролі.

Рядки матриці приходять із реєстру (app/rbac/registry.py), стан
перемикачів -- із role_permissions. Збереження -- JSON API після кожного
кліку (admin-access-matrix.js). CRUD ролей -- серверні форми (Task 12).
"""
from flask import (
    abort, current_app, flash, jsonify, redirect, render_template, request, url_for,
)
from flask_login import current_user
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.admin import admin_bp
from app.admin.forms import RoleForm
from app.extensions import db
from app.models.rbac import Role, UserRole
from app.rbac import permission_required, registry, service
from app.rbac.service import AccessError


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
    # type() is int, не isinstance: bool -- підклас int. Верхня межа -- bigint:
    # 10**30 інакше проходив до db.session.get і падав у Postgres 500-ю.
    if type(role_id) is not int or not 0 < role_id < _BIGINT_MAX:
        return None, data, (jsonify(error='role_id має бути цілим числом'), 400)
    role = db.session.get(Role, role_id)
    if role is None:
        return None, data, (jsonify(error='Роль не знайдено'), 404)
    return role, data, None


_BIGINT_MAX = 2 ** 63


def _apply(change):
    """Виконати зміну матриці й закомітити, завжди відповідаючи JSON.

    AccessError -- очікувана відмова запобіжника (400 з текстом). Будь-який
    інший виняток на збереженні раніше віддавав HTML-500 із глобального
    хендлера, і клієнт показував «Сесія завершилась» на живій сесії.
    """
    try:
        payload = change()
        db.session.commit()
    except AccessError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception('RBAC: збій збереження матриці')
        return jsonify(error='Не вдалося зберегти зміну, спробуйте ще раз'), 500
    return jsonify(ok=True, **payload)


@admin_bp.route('/access/api/matrix', methods=['PUT'])
@permission_required('access.manage')
def access_matrix_toggle():
    role, data, error = _json_role()
    if error is not None:
        return error

    def change():
        service.set_role_permission(
            role, str(data.get('permission', '')), bool(data.get('granted')), current_user)
        return {'role_id': role.id,
                'role_count': _role_count(role, len(registry.ALL_PERMISSION_NAMES))}
    return _apply(change)


@admin_bp.route('/access/api/matrix/bulk', methods=['POST'])
@permission_required('access.manage')
def access_matrix_bulk():
    role, data, error = _json_role()
    if error is not None:
        return error
    mode = data.get('mode')
    if mode not in ('all', 'none'):
        return jsonify(error='mode має бути all або none'), 400
    module = str(data.get('module', ''))

    def change():
        granted = service.set_module_permissions(role, module, mode == 'all', current_user)
        return {'role_id': role.id, 'module': module, 'granted': granted,
                'role_count': _role_count(role, len(registry.ALL_PERMISSION_NAMES))}
    return _apply(change)


def _role_form(role=None):
    form = RoleForm(obj=role) if request.method == 'GET' else RoleForm()
    # «Скопіювати права з» є лише у формі створення; для редагування поле не
    # рендериться, і choices достатньо одного значення-заглушки, щоб
    # pre_validate прийняв дефолт 0. Права ролей тут не потрібні, тож без
    # selectinload.
    choices = [(0, 'Не копіювати')]
    if role is None:
        choices += [(r.id, r.display_name)
                    for r in Role.query.order_by(Role.sort_order, Role.display_name)]
    form.copy_from.choices = choices
    return form


@admin_bp.route('/access/roles/new', methods=['GET', 'POST'])
@permission_required('access.manage')
def access_role_new():
    form = _role_form()
    if form.validate_on_submit():
        copy_from = db.session.get(Role, form.copy_from.data) if form.copy_from.data else None
        try:
            service.create_role(form.name.data, form.display_name.data,
                                form.description.data, form.color.data,
                                form.sort_order.data, current_user, copy_from=copy_from)
            db.session.commit()
            flash(f'Роль «{form.display_name.data}» створено', 'success')
            return redirect(url_for('admin.access'))
        except AccessError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
    return render_template('admin/access_role_form.html', form=form, role=None)


@admin_bp.route('/access/roles/<int:role_id>/edit', methods=['GET', 'POST'])
@permission_required('access.manage')
def access_role_edit(role_id):
    role = db.session.get(Role, role_id)
    if role is None:
        abort(404)
    form = _role_form(role)
    if form.validate_on_submit():
        try:
            service.update_role(role, form.display_name.data, form.description.data,
                                form.color.data, form.sort_order.data, current_user,
                                name=form.name.data)
            db.session.commit()
            flash('Роль оновлено', 'success')
            return redirect(url_for('admin.access'))
        except AccessError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
    return render_template('admin/access_role_form.html', form=form, role=role)


def _role_action(role_id, action, success):
    role = db.session.get(Role, role_id)
    if role is None:
        abort(404)
    try:
        action(role, current_user)
        db.session.commit()
        flash(success, 'success')
    except AccessError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
    return redirect(url_for('admin.access'))


@admin_bp.route('/access/roles/<int:role_id>/delete', methods=['POST'])
@permission_required('access.manage')
def access_role_delete(role_id):
    return _role_action(role_id, service.delete_role, 'Роль видалено')


@admin_bp.route('/access/roles/<int:role_id>/reset', methods=['POST'])
@permission_required('access.manage')
def access_role_reset(role_id):
    return _role_action(role_id, service.reset_role_to_defaults,
                        'Права ролі повернуто до дефолтів')
