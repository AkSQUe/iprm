"""Admin routes for event XLSX import/export."""

import logging
from io import BytesIO

from urllib.parse import quote

from flask import flash, redirect, request, send_file, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.services.event_excel_service import (
    export_events_to_xlsx,
    import_events_from_xlsx,
)

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
    file = request.files.get('file')
    if not file or not file.filename:
        flash('\u0424\u0430\u0439\u043b \u043d\u0435 \u043e\u0431\u0440\u0430\u043d\u043e', 'error')
        return redirect(url_for('admin.events_list'))

    if not file.filename.lower().endswith('.xlsx'):
        flash('\u041f\u0456\u0434\u0442\u0440\u0438\u043c\u0443\u044e\u0442\u044c\u0441\u044f \u043b\u0438\u0448\u0435 .xlsx \u0444\u0430\u0439\u043b\u0438', 'error')
        return redirect(url_for('admin.events_list'))

    file_data = file.read()
    if len(file_data) > MAX_IMPORT_SIZE:
        flash(f'\u0424\u0430\u0439\u043b \u0437\u0430\u043d\u0430\u0434\u0442\u043e \u0432\u0435\u043b\u0438\u043a\u0438\u0439 (\u043c\u0430\u043a\u0441. {MAX_IMPORT_SIZE // 1024 // 1024} \u041c\u0411)', 'error')
        return redirect(url_for('admin.events_list'))

    file_stream = BytesIO(file_data)
    stats = import_events_from_xlsx(file_stream, current_user.id)

    if stats['created'] or stats['updated']:
        flash(
            f"\u0406\u043c\u043f\u043e\u0440\u0442 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e: {stats['created']} \u0441\u0442\u0432\u043e\u0440\u0435\u043d\u043e, "
            f"{stats['updated']} \u043e\u043d\u043e\u0432\u043b\u0435\u043d\u043e",
            'success',
        )
    elif not stats['errors']:
        flash('\u041d\u0435 \u0437\u043d\u0430\u0439\u0434\u0435\u043d\u043e \u0434\u0430\u043d\u0438\u0445 \u0434\u043b\u044f \u0456\u043c\u043f\u043e\u0440\u0442\u0443', 'warning')

    for error in stats['errors']:
        flash(error, 'error')

    audit_logger.info(
        'Admin %s imported events: created=%d, updated=%d, errors=%d',
        current_user.email,
        stats['created'],
        stats['updated'],
        len(stats['errors']),
    )
    return redirect(url_for('admin.events_list'))
