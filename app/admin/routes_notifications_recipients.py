"""Admin: керування одержувачами admin-нотифікацій.

GET  /admin/notifications/recipients                       -- форма
POST /admin/notifications/recipients                       -- зберегти правила
POST /admin/notifications/recipients/managers              -- глобальний пул менеджерів
POST /admin/notifications/recipients/test/<event_type>     -- тест-надсилання
GET  /admin/notifications/recipients/preview               -- JSON для live-preview
"""
import logging
import re

from flask import (
    abort, flash, jsonify, redirect, render_template, request, url_for,
)
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.notification_rule import (
    DEFAULT_TRIGGER_STATUSES, EVENT_TYPES, NotificationRule,
)
from app.models.site_settings import SiteSettings
from app.services import notification_recipients


logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

# Сильніша валідація email ніж "є @". Не претендуємо на повну RFC 5322,
# але відкидаємо "@foo", "x@y" без TLD, тощо.
EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')

# Дозволені status-переходи для status_change (підмножина EventRegistration.STATUSES).
ALLOWED_TRIGGER_STATUSES = {'pending', 'confirmed', 'completed', 'cancelled'}


def _parse_emails(raw):
    """Текстове поле -> list[str]. Дозволяємо коми, нові рядки, пробіли;
    кожен токен фільтруємо EMAIL_RE. Невалідні токени тихо відкидаємо
    (поле admin-only). Dedup із збереженням порядку."""
    if not raw:
        return []
    chunks = (raw or '').replace(',', '\n').splitlines()
    seen = set()
    out = []
    for chunk in chunks:
        email = chunk.strip().lower()
        if not email or not EMAIL_RE.match(email):
            continue
        if email not in seen:
            seen.add(email)
            out.append(email)
    return out


def _parse_trigger_statuses(raw_list):
    """Список значень з POST -> list[str]; лишаємо лише дозволені."""
    out = []
    seen = set()
    for v in raw_list or []:
        s = (v or '').strip()
        if s in ALLOWED_TRIGGER_STATUSES and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _ensure_rule(event_type):
    """Race-safe upsert: SELECT, якщо немає -- INSERT + commit, обробка
    IntegrityError від конкурентного INSERT (повторний SELECT)."""
    rule = NotificationRule.query.get(event_type)
    if rule is not None:
        return rule

    rule = NotificationRule(event_type=event_type)
    db.session.add(rule)
    try:
        db.session.commit()
        return rule
    except IntegrityError:
        # Інший запит встиг створити рядок -- повторюємо SELECT.
        db.session.rollback()
        rule = NotificationRule.query.get(event_type)
        if rule is None:
            # Не мало б статися, але краще явна 500-помилка ніж тиха гонка.
            raise RuntimeError(
                f'ensure_rule({event_type!r}): IntegrityError on insert '
                f'but row still missing after rollback'
            )
        return rule


def _load_rules_map():
    """{event_type: NotificationRule} race-safe. Кожен відсутній рядок
    створюється через _ensure_rule, що ловить конкурентний INSERT."""
    rules = {r.event_type: r for r in NotificationRule.query.all()}
    for event_type, _ in EVENT_TYPES:
        if event_type not in rules:
            rules[event_type] = _ensure_rule(event_type)
    return rules


@admin_bp.route('/notifications/recipients', methods=['GET'])
@admin_required
def notifications_recipients():
    rules_map = _load_rules_map()
    settings = SiteSettings.get()

    # Превʼю одержувачів на момент відкриття форми (без instance/status
    # фільтрів -- агрегований "тепер з цими правилами охопить N людей").
    previews = {
        et: notification_recipients.preview(et)
        for et, _ in EVENT_TYPES
    }

    return render_template(
        'admin/notifications_recipients.html',
        event_types=EVENT_TYPES,
        rules=rules_map,
        manager_emails=settings.event_manager_emails or [],
        previews=previews,
        default_trigger_statuses=DEFAULT_TRIGGER_STATUSES,
        allowed_trigger_statuses=sorted(ALLOWED_TRIGGER_STATUSES),
    )


@admin_bp.route('/notifications/recipients', methods=['POST'])
@admin_required
def notifications_recipients_save():
    rules_map = _load_rules_map()
    changed = []
    for event_type, _ in EVENT_TYPES:
        rule = rules_map[event_type]
        prefix = f'rule__{event_type}__'
        new_enabled = request.form.get(prefix + 'enabled') == 'on'
        new_admins = request.form.get(prefix + 'notify_admins') == 'on'
        new_managers = request.form.get(prefix + 'notify_managers') == 'on'
        new_trainer = request.form.get(prefix + 'notify_event_trainer') == 'on'
        new_extra = _parse_emails(request.form.get(prefix + 'extra_emails'))

        new_trigger_statuses = None
        if event_type == 'status_change':
            new_trigger_statuses = _parse_trigger_statuses(
                request.form.getlist(prefix + 'trigger_statuses')
            )
            if not new_trigger_statuses:
                # Порожній список = повернути дефолт ['cancelled'] щоб
                # випадково не вимкнути всю секцію (для повного offу є
                # окремий прапор enabled).
                new_trigger_statuses = list(DEFAULT_TRIGGER_STATUSES)

        snapshot = (
            rule.enabled, rule.notify_admins, rule.notify_managers,
            rule.notify_event_trainer, list(rule.extra_emails or []),
            list(rule.trigger_statuses or []) if rule.trigger_statuses else None,
        )
        new_snapshot = (
            new_enabled, new_admins, new_managers, new_trainer, new_extra,
            new_trigger_statuses,
        )
        if snapshot != new_snapshot:
            rule.enabled = new_enabled
            rule.notify_admins = new_admins
            rule.notify_managers = new_managers
            rule.notify_event_trainer = new_trainer
            rule.extra_emails = new_extra
            if event_type == 'status_change':
                rule.trigger_statuses = new_trigger_statuses
            changed.append(event_type)

    try:
        db.session.commit()
        if changed:
            audit_logger.info(
                'Admin %s updated notification rules: %s',
                current_user.email, ', '.join(changed),
            )
            flash(f'Збережено правила: {", ".join(changed)}', 'success')
        else:
            flash('Без змін', 'info')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to save notification rules')
        flash('Помилка при збереженні', 'error')
    return redirect(url_for('admin.notifications_recipients'))


@admin_bp.route('/notifications/recipients/managers', methods=['POST'])
@admin_required
def notifications_recipients_managers_save():
    settings = SiteSettings.get()
    new_emails = _parse_emails(request.form.get('manager_emails'))
    if (settings.event_manager_emails or []) == new_emails:
        flash('Список менеджерів без змін', 'info')
        return redirect(url_for('admin.notifications_recipients'))
    try:
        settings.event_manager_emails = new_emails
        db.session.commit()
        audit_logger.info(
            'Admin %s updated event_manager_emails: %d address(es)',
            current_user.email, len(new_emails),
        )
        flash(f'Збережено: {len(new_emails)} адрес менеджерів', 'success')
    except Exception:
        db.session.rollback()
        logger.exception('Failed to save event_manager_emails')
        flash('Помилка при збереженні', 'error')
    return redirect(url_for('admin.notifications_recipients'))


@admin_bp.route('/notifications/recipients/test/<event_type>', methods=['POST'])
@admin_required
def notifications_recipients_test(event_type):
    """Надіслати тестовий admin-лист на поточних резолвнутих одержувачів.

    Контекст -- синтетичний (мінімальний): без registration/event,
    лише kind_label="ТЕСТ: <подія>" + admin_url на список реєстрацій.
    Мета -- перевірити, що (1) правила резолвляться правильно, (2) SMTP
    реально шле, (3) сповіщення приходять у потрібні поштові скриньки.
    """
    if event_type not in dict(EVENT_TYPES):
        abort(404)

    # Для status_change тестуємо з 'cancelled' (дефолтний trigger).
    test_new_status = 'cancelled' if event_type == 'status_change' else None
    recipients = notification_recipients.resolve(
        event_type, instance=None, new_status=test_new_status,
    )
    if not recipients:
        flash(
            'Немає одержувачів для тесту: правило вимкнено або всі джерела порожні',
            'warning',
        )
        return redirect(url_for('admin.notifications_recipients'))

    from app.services.email_service import EmailService
    label = dict(EVENT_TYPES).get(event_type, event_type)
    settings = SiteSettings.get()
    base = (settings.website_url or '').rstrip('/')
    admin_url = f'{base}/admin/notifications/recipients' if base \
        else '/admin/notifications/recipients'
    sent = 0
    for to in recipients:
        try:
            EmailService.send_email(
                to=to,
                subject=f'[ТЕСТ] {label}',
                template_name='admin_event_notification',
                context={
                    'kind_label': f'ТЕСТ: {label}',
                    'admin_url': admin_url,
                    'registration': None,
                    'event': None,
                },
                trigger=event_type,
            )
            sent += 1
        except Exception:
            logger.exception(
                'test-send: failed to send to %s for event_type=%s',
                to, event_type,
            )
    audit_logger.info(
        'Admin %s sent test admin-notification for %s to %d recipients',
        current_user.email, event_type, sent,
    )
    flash(
        f'Тестовий лист надіслано на {sent} з {len(recipients)} адрес ({label})',
        'success' if sent else 'warning',
    )
    return redirect(url_for('admin.notifications_recipients'))


@admin_bp.route('/notifications/recipients/preview', methods=['GET'])
@admin_required
def notifications_recipients_preview():
    """JSON-endpoint для live-preview одержувачів. Не змінює стан --
    лише читає поточні правила і повертає breakdown.

    Query params:
      event_type=registration|payment|course_request|status_change
      instance_id=<int> (опційний) -- зрезолвити тренера для конкретного instance
      new_status=<str> (опційний) -- для status_change перевірити trigger_statuses
    """
    event_type = request.args.get('event_type', '').strip()
    if event_type not in dict(EVENT_TYPES):
        return jsonify({'ok': False, 'error': 'unknown_event_type'}), 400

    instance = None
    instance_id = request.args.get('instance_id', type=int)
    if instance_id:
        instance = db.session.get(CourseInstance, instance_id)

    new_status = request.args.get('new_status') or None

    data = notification_recipients.preview(
        event_type, instance=instance, new_status=new_status,
    )
    return jsonify({'ok': True, 'event_type': event_type, **data})
