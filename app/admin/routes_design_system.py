"""Admin: каталог дизайн-системи.

Каталог показує компоненти ЖИВИМИ -- підключає ті самі CSS-файли, з яких
малюються справжні сторінки. Тому він ламається разом із компонентом, якщо
той зламали, і тёмна тема перевіряється сама собою.

Жив на публічному /design-system із noindex; переїхав в адмінку, бо це
інструмент розробки, а не сторінка сайту. Стара адреса лишилась редиректом.
"""
from flask import render_template

from app.admin import admin_bp
from app.admin.decorators import admin_required


@admin_bp.route('/design-system')
@admin_required
def design_system():
    return render_template('admin/design_system.html')
