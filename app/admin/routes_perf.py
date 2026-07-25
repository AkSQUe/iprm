"""Admin: перегляд замірів швидкості завантаження сторінок.

Адмінка НЕ вимірює -- вона показує те, що надіслав tools/perf/perf_check.py
(причина в докстрінгу app/models/perf_run.py). Тут: список прогонів, детальний
розбір одного прогону з порівнянням із попереднім, ротація ключа приймання.
"""
import logging
import secrets

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin._helpers import rotation_status
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.perf_run import PerfRun
from app.models.site_settings import SiteSettings
from app.models.mixins import utcnow
from app.services import perf_service

audit_logger = logging.getLogger('audit')

PER_PAGE = 20


def _key_state():
    """Стан ключа приймання для шапки сторінки."""
    settings = SiteSettings.get()
    present = bool(settings.perf_api_key)
    return {
        'present': present,
        'set_at': settings.perf_api_key_set_at,
        'rotation': rotation_status(
            settings.perf_api_key_set_at, is_secret_present=present,
        ),
        'ingest_url': url_for('api_v1.perf_run_create', _external=True),
    }


@admin_bp.route('/perf')
@admin_required
def perf_runs():
    page = request.args.get('page', 1, type=int)
    pagination = (
        PerfRun.query
        .order_by(PerfRun.measured_at.desc(), PerfRun.id.desc())
        .paginate(page=page, per_page=PER_PAGE, error_out=False)
    )

    latest = pagination.items[0] if page == 1 and pagination.items else None
    latest_comparison = {}
    if latest is not None:
        latest_comparison = perf_service.compare(latest, perf_service.previous_run(latest))

    return render_template(
        'admin/perf_runs.html',
        runs=pagination.items,
        pagination=pagination,
        latest=latest,
        latest_regressions=perf_service.regression_count(latest_comparison),
        key_state=_key_state(),
    )


@admin_bp.route('/perf/<int:run_id>')
@admin_required
def perf_run_detail(run_id):
    run = PerfRun.query.get_or_404(run_id)
    base = perf_service.previous_run(run)
    comparison = perf_service.compare(run, base)

    return render_template(
        'admin/perf_run_detail.html',
        run=run,
        base=base,
        comparison=comparison,
        regressions=perf_service.regression_count(comparison),
        metrics=perf_service.COMPARED_METRICS,
    )


@admin_bp.route('/perf/<int:run_id>/delete', methods=['POST'])
@admin_required
def perf_run_delete(run_id):
    run = PerfRun.query.get_or_404(run_id)
    db.session.delete(run)
    db.session.commit()
    audit_logger.info('Admin %s deleted perf run #%d', current_user.email, run_id)
    flash('Прогін видалено.', 'success')
    return redirect(url_for('admin.perf_runs'))


@admin_bp.route('/perf/key/rotate', methods=['POST'])
@admin_required
def perf_key_rotate():
    settings = SiteSettings.get()
    key = secrets.token_urlsafe(32)
    settings.perf_api_key = key
    settings.perf_api_key_set_at = utcnow()
    db.session.commit()
    audit_logger.warning('Admin %s rotated perf ingest key', current_user.email)
    # Ключ показуємо один раз: сторінка його більше не виводить, тож
    # адміністратор має скопіювати його зараз.
    flash(f'Новий ключ приймання (скопіюйте зараз, повторно не показуємо): {key}', 'success')
    return redirect(url_for('admin.perf_runs'))


@admin_bp.route('/perf/key/clear', methods=['POST'])
@admin_required
def perf_key_clear():
    settings = SiteSettings.get()
    settings.perf_api_key = ''
    settings.perf_api_key_set_at = None
    db.session.commit()
    audit_logger.warning('Admin %s cleared perf ingest key', current_user.email)
    flash('Приймання замірів вимкнено -- ендпоінт більше не приймає дані.', 'warning')
    return redirect(url_for('admin.perf_runs'))
