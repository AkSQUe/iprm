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

from app.admin import _listing, admin_bp
from app.admin._helpers import rotation_status
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.perf_run import PerfRun, VERDICT_FAIL, VERDICT_OK, VERDICT_WARN
from app.models.site_settings import SiteSettings
from app.models.mixins import utcnow
from app.services import perf_service
from app.utils import ensure_utc

audit_logger = logging.getLogger('audit')

PER_PAGE = 20

# Підписи -- самі значення вердикту, нових не вигадуємо: саме так вони й
# друкуються в бейджі/картці (app/models/perf_run.py).
_VERDICT_CHOICES = {VERDICT_OK: VERDICT_OK, VERDICT_WARN: VERDICT_WARN, VERDICT_FAIL: VERDICT_FAIL}


def _source_choices():
    """Перелік джерел, що фактично трапляються в БД (не вигаданий список).

    Прогони з різних джерел (машина, "local", "ci") непорівнянні між собою --
    див. коментар до колонки `source` у app/models/perf_run.py:76-78.
    """
    rows = (
        db.session.query(PerfRun.source)
        .filter(PerfRun.source.isnot(None), PerfRun.source != '')
        .distinct()
        .order_by(PerfRun.source)
        .all()
    )
    return {source: source for (source,) in rows}


def _filters(source_choices=None):
    if source_choices is None:
        source_choices = _source_choices()
    return {
        'q': _listing.text_arg('q'),
        'verdict': _listing.choice_arg('verdict', _VERDICT_CHOICES),
        'source': _listing.choice_arg('source', source_choices),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
    }

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
    page = _listing.page_arg()
    source_choices = _source_choices()
    filters = _filters(source_choices)
    filter_args = _listing.filter_args(filters)

    query = PerfRun.query
    if filters['verdict']:
        query = query.filter(PerfRun.verdict == filters['verdict'])
    if filters['source']:
        query = query.filter(PerfRun.source == filters['source'])
    query = _listing.apply_date_range(
        query, PerfRun.measured_at, filters['date_from'], filters['date_to'],
    )
    query = _listing.apply_search(query, filters['q'], [PerfRun.note, PerfRun.base_url])

    pagination = (
        query
        .order_by(PerfRun.measured_at.desc(), PerfRun.id.desc())
        .paginate(page=page, per_page=PER_PAGE, error_out=False)
    )

    # Під активним фільтром перший рядок сторінки 1 більше НЕ найновіший
    # прогін узагалі -- лише найновіший у зрізі. Блок порівняння в шапці
    # підписаний як "останній замір", тож під фільтром він просто не малюється
    # -- так само, як уже не малюється на другій сторінці без фільтра.
    latest = (
        pagination.items[0]
        if page == 1 and not filter_args and pagination.items
        else None
    )
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
        filters=filters,
        filter_args=filter_args,
        back_args=_listing.back_args(filter_args, pagination.page),
        verdict_options=list(_VERDICT_CHOICES.items()),
        source_options=list(source_choices.items()),
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

    # Фільтр звужує лише таблиці сторінок нижче -- інший рівень зрізу, ніж
    # verdict у списку прогонів (той фільтрує РЯДКИ /admin/perf). Картки-
    # лічильники, порівняння й найповільніша сторінка лишаються по всьому
    # прогону: вони підписані як стан прогону, а не показаного зрізу.
    page_verdict = _listing.choice_arg('verdict', _VERDICT_CHOICES)
    pages = [p for p in run.pages if p.verdict == page_verdict] if page_verdict else run.pages

    return render_template(
        'admin/perf_run_detail.html',
        run=run,
        pages=pages,
        page_verdict=page_verdict,
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
    # Зріз береться з query string самого запиту дії -- action-URL у шаблоні
    # несе його через back_args, зібраний тим самим _listing.back_args, що й
    # у списку. Той самий шаблон, що для webhooks/blog_comments.
    return _listing.back_redirect('admin.perf_runs', _filters())


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
    flash('Приймання замірів вимкнено – ендпоінт більше не приймає дані.', 'warning')
    return redirect(url_for('admin.perf_runs'))
