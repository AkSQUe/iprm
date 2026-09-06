"""Адмінка: налаштування інтеграції з Sintegrum.

GET  /admin/sintegrum        -- статус, маскований ключ, форма, останній прогін
POST /admin/sintegrum/save   -- зберегти налаштування (порожній ключ не затирає)
POST /admin/sintegrum/test   -- перевірка зв'язку (ping каталогу)
POST /admin/sintegrum/sync   -- ручна синхронізація каталогу

Керування самими курсами -- окрема сторінка (routes_online_courses).
Тут лише те, що стосується з'єднання з чужою системою.
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin._helpers import mask_secret, save_integration_settings
from app.rbac import permission_required
from app.extensions import limiter
from app.models.mixins import utcnow
from app.models.online_course import OnlineCourse
from app.models.site_settings import SiteSettings
from app.services.sintegrum_client import SintegrumClient, SintegrumConfigError

audit_logger = logging.getLogger('audit')

MIN_SYNC_INTERVAL_MINUTES = 5
MAX_SYNC_INTERVAL_MINUTES = 1440
MIN_ACCESS_TTL_HOURS = 1
MAX_ACCESS_TTL_HOURS = 24 * 30
# 0 -- не нагадувати взагалі (той самий сенс, що в certdata_reminder_days).
MIN_REMINDER_DAYS = 0
MAX_REMINDER_DAYS = 60


def _config(settings):
    return {
        'enabled': settings.sintegrum_enabled,
        'show_section': settings.show_online_courses,
        'base_url': settings.sintegrum_api_base_url or '',
        'company_alias': settings.sintegrum_company_alias or '',
        # У шаблон іде лише маска -- сам ключ не залишає серверний код.
        'api_key_masked': mask_secret(settings.sintegrum_api_key),
        'api_key_is_set': settings.sintegrum_api_key_is_set,
        'api_key_set_at': settings.sintegrum_api_key_set_at,
        'sync_interval': settings.sintegrum_sync_interval_minutes,
        'access_ttl': settings.sintegrum_access_ttl_hours,
        'reminder_days': settings.sintegrum_access_reminder_days,
        'last_sync_at': settings.sintegrum_last_sync_at,
        'last_sync_status': settings.sintegrum_last_sync_status or '',
        'last_sync_error': settings.sintegrum_last_sync_error or '',
        'is_configured': bool(
            settings.sintegrum_api_key_is_set
            and (settings.sintegrum_company_alias or '').strip()
            and (settings.sintegrum_api_base_url or '').strip()
        ),
        'courses_total': OnlineCourse.query.count(),
        'courses_published': OnlineCourse.query.filter_by(is_published=True).count(),
        'courses_vanished': OnlineCourse.query.filter_by(is_vanished=True).count(),
    }


@admin_bp.route('/sintegrum')
@permission_required('integrations.view')
def sintegrum():
    settings = SiteSettings.get()
    return render_template('admin/sintegrum.html', cfg=_config(settings))


@admin_bp.route('/sintegrum/save', methods=['POST'])
@permission_required('integrations.keys')
def sintegrum_save():
    settings = SiteSettings.get()

    base_url = request.form.get('base_url', '').strip()
    company_alias = request.form.get('company_alias', '').strip()
    api_key = request.form.get('api_key', '').strip()
    enabled = request.form.get('enabled') == 'on'

    def _int_field(name, default, low, high, label):
        raw = request.form.get(name, '').strip()
        if not raw:
            return default, None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None, f'{label}: очікується ціле число'
        if not low <= value <= high:
            return None, f'{label}: допустимий діапазон {low}..{high}'
        return value, None

    interval, err = _int_field(
        'sync_interval', settings.sintegrum_sync_interval_minutes,
        MIN_SYNC_INTERVAL_MINUTES, MAX_SYNC_INTERVAL_MINUTES,
        'Інтервал синхронізації',
    )
    if err:
        flash(err, 'error')
        return redirect(url_for('admin.sintegrum'))

    ttl, err = _int_field(
        'access_ttl', settings.sintegrum_access_ttl_hours,
        MIN_ACCESS_TTL_HOURS, MAX_ACCESS_TTL_HOURS,
        'Термін дії посилання',
    )
    if err:
        flash(err, 'error')
        return redirect(url_for('admin.sintegrum'))

    reminder_days, err = _int_field(
        'reminder_days', settings.sintegrum_access_reminder_days,
        MIN_REMINDER_DAYS, MAX_REMINDER_DAYS,
        'Нагадування про невикористаний курс',
    )
    if err:
        flash(err, 'error')
        return redirect(url_for('admin.sintegrum'))

    if base_url and not base_url.startswith('https://'):
        # Ключ їде в заголовку кожного запиту -- по http він поїхав би відкритим.
        flash('Базовий URL має починатися з https://', 'error')
        return redirect(url_for('admin.sintegrum'))

    # Перевіряємо стан ПІСЛЯ збереження: порожнє поле ключа означає
    # "лишити наявний", тож увімкнення не має падати через нього.
    final_key_present = bool(api_key) or settings.sintegrum_api_key_is_set
    if enabled and not (base_url and company_alias and final_key_present):
        flash(
            'Щоб увімкнути інтеграцію, потрібні базовий URL, аліас компанії і ключ API',
            'error',
        )
        return redirect(url_for('admin.sintegrum'))

    updates = {
        'sintegrum_api_base_url': base_url,
        'sintegrum_company_alias': company_alias,
        'sintegrum_enabled': enabled,
        'show_online_courses': request.form.get('show_section') == 'on',
        'sintegrum_sync_interval_minutes': interval,
        'sintegrum_access_ttl_hours': ttl,
        'sintegrum_access_reminder_days': reminder_days,
    }
    if api_key:
        updates['sintegrum_api_key'] = api_key
        updates['sintegrum_api_key_set_at'] = utcnow()

    save_integration_settings(
        provider='sintegrum',
        settings=settings,
        updates=updates,
        audit_summary={
            'enabled': enabled,
            'company_alias': company_alias,
            'api_key_changed': bool(api_key),
            'sync_interval': interval,
            'access_ttl': ttl,
            'reminder_days': reminder_days,
        },
        success_msg='Налаштування Sintegrum збережено',
    )
    return redirect(url_for('admin.sintegrum'))


@admin_bp.route('/sintegrum/test', methods=['POST'])
@permission_required('integrations.manage')
@limiter.limit('10 per minute')
def sintegrum_test():
    """Перевірка зв'язку. Працює і при вимкненій інтеграції -- інакше
    перевірити ключ можна було б лише після його активації."""
    settings = SiteSettings.get()
    try:
        client = SintegrumClient(
            settings.sintegrum_api_base_url,
            settings.sintegrum_company_alias,
            settings.sintegrum_api_key,
        )
        if not (client.base_url and client.company and client.api_key):
            raise SintegrumConfigError(
                'Заповніть базовий URL, аліас компанії і ключ API',
            )
    except SintegrumConfigError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin.sintegrum'))

    result = client.ping()
    audit_logger.info(
        'Admin %s tested Sintegrum connection: ok=%s status=%s',
        current_user.email, result.ok, result.http_status,
    )

    if result.ok:
        flash(
            f'Зв\'язок є: каталог компанії "{client.company}" читається',
            'success',
        )
    else:
        flash(result.error or 'Не вдалося з\'єднатися з Sintegrum', 'error')

    return redirect(url_for('admin.sintegrum'))


@admin_bp.route('/sintegrum/sync', methods=['POST'])
@permission_required('integrations.manage')
@limiter.limit('10 per minute')
def sintegrum_sync():
    from app.services.online_course_sync import sync_courses

    # Без обкладинок: вони тягнуться по HTTP на кожен курс, і адмін чекав би
    # на це в браузері. Каталог оновиться повністю, картинки підбере
    # найближчий плановий прогін.
    report = sync_courses(with_covers=False)
    audit_logger.info(
        'Admin %s ran Sintegrum sync manually: %s',
        current_user.email, report.summary,
    )

    if report.ok:
        flash(f'Синхронізацію виконано. {report.summary}. '
              'Обкладинки підтягне фонове оновлення.', 'success')
    else:
        flash(f'Синхронізація не вдалася. {report.summary}', 'error')

    return redirect(url_for('admin.sintegrum'))
