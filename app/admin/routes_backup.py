"""Admin: database backup management."""
import logging

from flask import render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.admin.decorators import admin_required
from app.models.database_backup import DatabaseBackup

audit_logger = logging.getLogger('audit')


@admin_bp.route('/backups')
@admin_required
def backups():
    page = _listing.page_arg()
    per_page = 20

    from app.services.backup_service import BackupService
    stats = BackupService.get_storage_stats()

    pagination = (
        DatabaseBackup.query
        .order_by(DatabaseBackup.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return render_template(
        'admin/backups.html',
        backups=pagination.items,
        pagination=pagination,
        stats=stats,
    )


@admin_bp.route('/backups/create', methods=['POST'])
@admin_required
def backup_create():
    from app.extensions import db
    from app.services.backup_service import BackupService, BackupError, BackupConcurrencyError

    backup_type = request.form.get('backup_type', 'full')
    description = request.form.get('description', '')

    if backup_type not in DatabaseBackup.TYPES:
        flash('Невідомий тип резервної копії.', 'error')
        return redirect(url_for('admin.backups'))

    try:
        backup = BackupService.create_backup(
            backup_type=backup_type,
            description=description,
            created_by_id=current_user.id,
        )
        audit_logger.info(
            'Admin %s created backup #%d (%s)',
            current_user.email, backup.id, backup_type,
        )
        flash(f'Резервну копію створено: {backup.filename} ({backup.file_size_display})', 'success')
    except BackupConcurrencyError:
        flash('Досягнуто максимум одночасних операцій. Спробуйте пізніше.', 'warning')
    except BackupError as exc:
        flash(f'Помилка створення резервної копії: {exc}', 'error')
        audit_logger.exception('Admin %s backup creation failed', current_user.email)

    return redirect(url_for('admin.backups'))


@admin_bp.route('/backups/<int:backup_id>/restore', methods=['POST'])
@admin_required
def backup_restore(backup_id):
    from app.services.backup_service import BackupService, BackupError

    force = request.form.get('force') == 'true'

    try:
        BackupService.restore_backup(backup_id, force=force, created_by_id=current_user.id)
        audit_logger.warning(
            'Admin %s restored backup #%d', current_user.email, backup_id,
        )
        flash('Базу даних успішно відновлено.', 'success')
    except BackupError as exc:
        flash(f'Помилка відновлення: {exc}', 'error')
        audit_logger.exception('Admin %s restore failed for backup #%d', current_user.email, backup_id)

    return redirect(url_for('admin.backups'))


@admin_bp.route('/backups/<int:backup_id>/validate')
@admin_required
def backup_validate(backup_id):
    from app.services.backup_service import BackupService, BackupError

    try:
        valid = BackupService.validate_backup(backup_id)
        if valid:
            flash('Цілісність резервної копії підтверджена.', 'success')
        else:
            flash('Резервна копія пошкоджена!', 'error')
    except BackupError as exc:
        flash(f'Помилка валідації: {exc}', 'error')

    return redirect(url_for('admin.backups'))


@admin_bp.route('/backups/<int:backup_id>/delete', methods=['POST'])
@admin_required
def backup_delete(backup_id):
    from app.services.backup_service import BackupService, BackupError

    try:
        filename = DatabaseBackup.query.get(backup_id).filename
        BackupService.delete_backup(backup_id)
        audit_logger.info(
            'Admin %s deleted backup #%d (%s)', current_user.email, backup_id, filename,
        )
        flash('Резервну копію видалено.', 'success')
    except BackupError as exc:
        flash(f'Помилка видалення: {exc}', 'error')

    return redirect(url_for('admin.backups'))


@admin_bp.route('/backups/<int:backup_id>/download')
@admin_required
def backup_download(backup_id):
    backup = DatabaseBackup.query.get_or_404(backup_id)
    if backup.status != DatabaseBackup.STATUS_COMPLETED:
        flash('Можна завантажити лише успішні резервні копії.', 'error')
        return redirect(url_for('admin.backups'))

    import os
    if not os.path.exists(backup.file_path):
        flash('Файл резервної копії не знайдено на диску.', 'error')
        return redirect(url_for('admin.backups'))

    audit_logger.info(
        'Admin %s downloaded backup #%d', current_user.email, backup_id,
    )
    return send_file(
        backup.file_path,
        as_attachment=True,
        download_name=backup.filename,
        mimetype='application/octet-stream',
    )


@admin_bp.route('/backups/cleanup', methods=['POST'])
@admin_required
def backup_cleanup():
    from app.services.backup_service import BackupService

    dry_run = request.form.get('dry_run') == 'true'
    result = BackupService.cleanup_old_backups(dry_run=dry_run)

    if dry_run:
        flash(f'Dry run: буде видалено {result["would_delete"]} копій.', 'info')
    else:
        flash(f'Очищення завершено: видалено {result["deleted"]} старих копій.', 'success')
        audit_logger.info('Admin %s ran backup cleanup, deleted %d', current_user.email, result['deleted'])

    return redirect(url_for('admin.backups'))


@admin_bp.route('/backups/stats')
@admin_required
def backup_stats():
    from app.services.backup_service import BackupService
    stats = BackupService.get_storage_stats()
    return jsonify(stats)
