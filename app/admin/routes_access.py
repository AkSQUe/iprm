"""Сторінка «Доступ»: матриця прав і ролі. Повна версія -- Task 10 плану."""
from flask import render_template

from app.admin import admin_bp
from app.rbac import permission_required


@admin_bp.route('/access')
@permission_required('access.view')
def access():
    return render_template('admin/access.html')
