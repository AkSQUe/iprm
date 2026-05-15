"""Admin endpoints для експорту/імпорту xlsx (курси + проведення)."""
import logging
from datetime import datetime

from flask import (
    abort, flash, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.services import xlsx_io

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


# ----------------------------------------------------------------------
# COURSES
# ----------------------------------------------------------------------

@admin_bp.route('/courses/export')
@admin_required
def courses_export():
    """Експорт курсів. URL params:
      ?active=true   -- лише активні
      ?active=false  -- лише неактивні
      ?active=all (або без параметра) -- усі
    """
    active = request.args.get('active', 'all').lower()
    if active not in ('all', 'true', 'false'):
        active = 'all'
    data = xlsx_io.export_courses_xlsx(active=active)
    audit_logger.info(
        'Admin %s exported courses xlsx (active=%s)',
        current_user.email, active,
    )
    suffix = f'-active' if active == 'true' else ('-inactive' if active == 'false' else '')
    return send_file(
        data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'courses{suffix}-{datetime.now().strftime("%Y%m%d-%H%M")}.xlsx',
    )


@admin_bp.route('/courses/import', methods=['POST'])
@admin_required
def courses_import_upload():
    f = request.files.get('xlsx')
    if not f or not f.filename:
        flash('Оберіть файл .xlsx для завантаження', 'error')
        return redirect(url_for('admin.courses_list'))
    if not f.filename.lower().endswith('.xlsx'):
        flash('Формат файлу має бути .xlsx', 'error')
        return redirect(url_for('admin.courses_list'))

    token = xlsx_io.save_uploaded_xlsx(f)
    audit_logger.info(
        'Admin %s uploaded courses xlsx for preview (token=%s)',
        current_user.email, token,
    )
    return redirect(url_for('admin.courses_import_preview', token=token))


@admin_bp.route('/courses/import/preview/<token>')
@admin_required
def courses_import_preview(token):
    path = xlsx_io.get_uploaded_path(token)
    if path is None:
        flash('Файл імпорту не знайдено або сесія застаріла', 'error')
        return redirect(url_for('admin.courses_list'))

    plan = xlsx_io.parse_courses_xlsx(path)
    return render_template(
        'admin/xlsx_preview.html',
        entity='courses',
        token=token,
        plan=plan,
        apply_url=url_for('admin.courses_import_apply', token=token),
        cancel_url=url_for('admin.courses_import_cancel', token=token),
        back_url=url_for('admin.courses_list'),
        title='Імпорт курсів',
    )


@admin_bp.route('/courses/import/apply/<token>', methods=['POST'])
@admin_required
def courses_import_apply(token):
    path = xlsx_io.get_uploaded_path(token)
    if path is None:
        flash('Файл імпорту не знайдено або сесія застаріла', 'error')
        return redirect(url_for('admin.courses_list'))

    plan = xlsx_io.parse_courses_xlsx(path)
    if not plan.is_valid:
        flash(
            'У файлі є помилки валідації — імпорт відхилено. '
            'Виправте та завантажте знову.',
            'error',
        )
        return redirect(url_for('admin.courses_import_preview', token=token))

    result = xlsx_io.apply_courses_plan(plan)
    if result.get('ok'):
        xlsx_io.cleanup_upload(token)
        audit_logger.info(
            'Admin %s applied courses xlsx: created=%s updated=%s blocks=%s faq=%s',
            current_user.email,
            result.get('created'), result.get('updated'),
            result.get('blocks_touched'), result.get('faq_touched'),
        )
        flash(
            f'Імпорт виконано: створено {result["created"]}, '
            f'оновлено {result["updated"]}, програмних блоків {result["blocks_touched"]}, '
            f'FAQ-пунктів {result["faq_touched"]}.',
            'success',
        )
        return redirect(url_for('admin.courses_list'))

    flash(f'Помилка при збереженні: {result.get("reason")}', 'error')
    return redirect(url_for('admin.courses_import_preview', token=token))


@admin_bp.route('/courses/import/cancel/<token>', methods=['POST'])
@admin_required
def courses_import_cancel(token):
    xlsx_io.cleanup_upload(token)
    flash('Імпорт скасовано', 'info')
    return redirect(url_for('admin.courses_list'))


# ----------------------------------------------------------------------
# COURSE INSTANCES
# ----------------------------------------------------------------------

@admin_bp.route('/instances/export')
@admin_required
def instances_export():
    """Експорт розкладу. URL params:
      ?year=2026          -- лише цей рік
      ?upcoming=true      -- лише майбутні
      ?status=published   -- лише з вказаним статусом
    Параметри комбінуються.
    """
    year = request.args.get('year', type=int)
    upcoming = request.args.get('upcoming', '').lower() in ('true', '1', 'yes')
    status = request.args.get('status')
    if status and status not in {'draft', 'published', 'active', 'completed', 'cancelled'}:
        status = None

    data = xlsx_io.export_instances_xlsx(
        year=year, upcoming_only=upcoming, status=status,
    )
    audit_logger.info(
        'Admin %s exported instances xlsx (year=%s upcoming=%s status=%s)',
        current_user.email, year, upcoming, status,
    )

    parts = ['schedule']
    if year:
        parts.append(str(year))
    if upcoming:
        parts.append('upcoming')
    if status:
        parts.append(status)
    parts.append(datetime.now().strftime('%Y%m%d-%H%M'))
    return send_file(
        data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='-'.join(parts) + '.xlsx',
    )


@admin_bp.route('/instances/import', methods=['POST'])
@admin_required
def instances_import_upload():
    f = request.files.get('xlsx')
    if not f or not f.filename:
        flash('Оберіть файл .xlsx для завантаження', 'error')
        return redirect(url_for('admin.instances_list'))
    if not f.filename.lower().endswith('.xlsx'):
        flash('Формат файлу має бути .xlsx', 'error')
        return redirect(url_for('admin.instances_list'))

    token = xlsx_io.save_uploaded_xlsx(f)
    audit_logger.info(
        'Admin %s uploaded instances xlsx for preview (token=%s)',
        current_user.email, token,
    )
    return redirect(url_for('admin.instances_import_preview', token=token))


@admin_bp.route('/instances/import/preview/<token>')
@admin_required
def instances_import_preview(token):
    path = xlsx_io.get_uploaded_path(token)
    if path is None:
        flash('Файл імпорту не знайдено або сесія застаріла', 'error')
        return redirect(url_for('admin.instances_list'))

    plan = xlsx_io.parse_instances_xlsx(path)
    return render_template(
        'admin/xlsx_preview.html',
        entity='instances',
        token=token,
        plan=plan,
        apply_url=url_for('admin.instances_import_apply', token=token),
        cancel_url=url_for('admin.instances_import_cancel', token=token),
        back_url=url_for('admin.instances_list'),
        title='Імпорт розкладу',
    )


@admin_bp.route('/instances/import/apply/<token>', methods=['POST'])
@admin_required
def instances_import_apply(token):
    path = xlsx_io.get_uploaded_path(token)
    if path is None:
        flash('Файл імпорту не знайдено або сесія застаріла', 'error')
        return redirect(url_for('admin.instances_list'))

    plan = xlsx_io.parse_instances_xlsx(path)
    if not plan.is_valid:
        flash(
            'У файлі є помилки валідації — імпорт відхилено.',
            'error',
        )
        return redirect(url_for('admin.instances_import_preview', token=token))

    result = xlsx_io.apply_instances_plan(plan)
    if result.get('ok'):
        xlsx_io.cleanup_upload(token)
        audit_logger.info(
            'Admin %s applied instances xlsx: created=%s updated=%s',
            current_user.email,
            result.get('created'), result.get('updated'),
        )
        flash(
            f'Імпорт виконано: створено {result["created"]}, '
            f'оновлено {result["updated"]} проведень.',
            'success',
        )
        return redirect(url_for('admin.instances_list'))

    flash(f'Помилка при збереженні: {result.get("reason")}', 'error')
    return redirect(url_for('admin.instances_import_preview', token=token))


@admin_bp.route('/instances/import/cancel/<token>', methods=['POST'])
@admin_required
def instances_import_cancel(token):
    xlsx_io.cleanup_upload(token)
    flash('Імпорт скасовано', 'info')
    return redirect(url_for('admin.instances_list'))
