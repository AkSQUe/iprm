"""Admin routes for event XLSX import/export."""

import logging
from io import BytesIO

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


@admin_bp.route('/events/export')
@admin_required
def events_export():
    stream, filename = export_events_to_xlsx()
    audit_logger.info(
        'Admin %s exported events to XLSX', current_user.email,
    )
    return send_file(
        stream,
        as_attachment=True,
        download_name=filename,
        mimetype=XLSX_MIMETYPE,
    )


@admin_bp.route('/events/import', methods=['POST'])
@admin_required
def events_import():
    file = request.files.get('file')
    if not file or not file.filename:
        flash('File not selected', 'error')
        return redirect(url_for('admin.events_list'))

    if not file.filename.lower().endswith('.xlsx'):
        flash('Only .xlsx files are supported', 'error')
        return redirect(url_for('admin.events_list'))

    file_stream = BytesIO(file.read())
    stats = import_events_from_xlsx(file_stream, current_user.id)

    if stats['created'] or stats['updated']:
        flash(
            f"Import completed: {stats['created']} created, "
            f"{stats['updated']} updated",
            'success',
        )
    elif not stats['errors']:
        flash('No data found to import', 'warning')

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
