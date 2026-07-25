"""Admin: перегляд замірів швидкості завантаження сторінок.

Адмінка НЕ вимірює -- вона показує те, що надіслав tools/perf/perf_check.py
(причина в докстрінгу app/models/perf_run.py). Тут: список прогонів, детальний
розбір одного прогону з порівнянням із попереднім, ротація ключа приймання.
"""
import logging
import secrets

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import selectinload

from app.admin import admin_bp
from app.admin._helpers import rotation_status
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.perf_run import PerfRun
from app.models.site_settings import SiteSettings
from app.models.mixins import utcnow
from app.services import perf_service
from app.utils import ensure_utc

audit_logger = logging.getLogger('audit')

PER_PAGE = 20

# Пороги нагадування про ротацію (м'який / жорсткий, у днях). Ключ лише
# приймає телеметрію і не дає доступу до даних, тож пороги м'які -- як у
# reCAPTCHA. Передавати їх ОБОВ'ЯЗКОВО: без них rotation_status кидає ValueError.
KEY_ROTATION_DAYS = (365, 730)


def _key_state():
    """Стан ключа приймання для шапки сторінки."""
    settings = SiteSettings.get()
    present = bool(settings.perf_api_key)
    soft, hard = KEY_ROTATION_DAYS
    # ensure_utc обов'язковий: на SQLite дата повертається naive, а
    # rotation_status віднімає її від aware-now -> TypeError.
    set_at = ensure_utc(settings.perf_api_key_set_at)
    return {
        'present': present,
        'set_at': set_at,
        'rotation': rotation_status(
            set_at, soft_days=soft, hard_days=hard, is_secret_present=present,
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

    # Ключ показуємо лише одразу після генерації (?reveal=1). У flash його
    # класти не можна: flash живе у session-cookie, яка тільки підписана, а не
    # зашифрована, тож секрет осідав би у сховищі браузера у відкритому вигляді.
    reveal_key = ''
    if request.args.get('reveal') == '1':
        reveal_key = SiteSettings.get().perf_api_key

    return render_template(
        'admin/perf_runs.html',
        runs=pagination.items,
        pagination=pagination,
        latest=latest,
        latest_regressions=perf_service.regression_count(latest_comparison),
        key_state=_key_state(),
        reveal_key=reveal_key,
    )


@admin_bp.route('/perf/<int:run_id>')
@admin_required
def perf_run_detail(run_id):
    # Метрики тут потрібні гарантовано (і для таблиць, і для порівняння),
    # тож тягнемо їх одним selectin-запитом замість лінивого довантаження.
    run = (
        PerfRun.query
        .options(selectinload(PerfRun.pages))
        .filter(PerfRun.id == run_id)
        .first_or_404()
    )
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
    flash('Новий ключ приймання згенеровано. Старий більше не діє.', 'success')
    # Сам ключ передаємо через ?reveal=1, а не через flash: так він не
    # потрапляє у session-cookie і схема POST-redirect-GET лишається цілою
    # (оновлення сторінки не генерує ще один ключ).
    return redirect(url_for('admin.perf_runs', reveal=1))


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
