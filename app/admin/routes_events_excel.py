"""Admin routes for event XLSX import/export."""

import logging
from io import BytesIO

from urllib.parse import quote

from flask import flash, redirect, request, send_file, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.services.event_excel_service import export_events_to_xlsx

audit_logger = logging.getLogger('audit')

XLSX_MIMETYPE = (
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
)
MAX_IMPORT_SIZE = 10 * 1024 * 1024  # 10 MB


@admin_bp.route('/events/export')
@admin_required
def events_export():
    stream, filename = export_events_to_xlsx()
    audit_logger.info(
        'Admin %s exported events to XLSX', current_user.email,
    )
    response = send_file(
        stream,
        as_attachment=True,
        download_name=filename,
        mimetype=XLSX_MIMETYPE,
    )
    encoded = quote(filename)
    response.headers['Content-Disposition'] = (
        f"attachment; filename*=UTF-8''{encoded}"
    )
    return response


@admin_bp.route('/events/import', methods=['POST'])
@admin_required
def events_import():
    """Вимкнено після переходу на Course+CourseInstance.

    Імпорт у таблицю events створив би неконсистентність: нові записи
    з'являлися б у legacy-таблиці, але не в courses/course_instances,
    які використовуються публічною частиною й API. Для масового
    імпорту/оновлення курсів доведеться реалізувати адаптовану
    версію імпорту під нову модель (окрема задача).
    """
    flash(
        'Імпорт XLSX тимчасово вимкнено. Використайте "Курси" в адмінці '
        'для створення/редагування курсів, або дочекайтеся нової версії '
        'імпорту під Course+CourseInstance.',
        'warning',
    )
    return redirect(url_for('admin.courses_list'))
