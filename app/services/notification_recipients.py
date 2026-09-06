"""Резолвер одержувачів admin-нотифікації.

Публічний API:
  resolve(event_type, instance=None, new_status=None) -> list[str]
  preview(event_type, instance=None, new_status=None) -> dict

Джерела (комбінуються згідно з прапорами у NotificationRule):
  - notify_admins -> усі активні користувачі з правом notifications.receive (super_admin включно)
  - notify_managers -> SiteSettings.event_manager_emails
  - notify_event_trainer -> instance.effective_trainer.email
  - extra_emails завжди додаються (текстова конфігурація на правило)

Fail-soft: будь-яка DB-помилка під час резолва ловиться, логиується,
повертається [] -- caller-flow (наприклад, надсилання user-листа)
не падає від проблем з admin-нотифікацією.

Якщо правило відключене (enabled=False) -- повертаємо [].
Якщо event_type='status_change' і new_status не у trigger_statuses
правила -- повертаємо []. Це дозволяє адміну налаштувати, на які
переходи реагувати.
"""
import logging
import re

logger = logging.getLogger(__name__)

# Простий, але строгіший за "@" перевірник email (admin-форма, не
# user-input; не претендуємо на повну RFC 5322 валідацію).
EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')


def _normalize(email):
    if not email:
        return None
    email = str(email).strip().lower()
    if not email or not EMAIL_RE.match(email):
        return None
    return email


def _resolve_sources(event_type, instance, new_status):
    """Внутрішня логіка резолва. Винесена окремо щоб preview() міг
    повернути BREAKDOWN по джерелах (показати адміну ХТО куди прийде)."""
    # Імпорт у функцію щоб уникнути імпорт-циклів і дешеве lazy.
    from app.models.notification_rule import NotificationRule
    from app.models.site_settings import SiteSettings

    rule = NotificationRule.get_or_stub(event_type)
    if not rule.enabled:
        return rule, None, {'admins': [], 'managers': [], 'trainer': [], 'extra': []}

    # Для status_change шануємо trigger_statuses фільтр.
    if event_type == 'status_change' and new_status is not None:
        if new_status not in rule.effective_trigger_statuses:
            return rule, 'status_not_in_triggers', {
                'admins': [], 'managers': [], 'trainer': [], 'extra': [],
            }

    breakdown = {'admins': [], 'managers': [], 'trainer': [], 'extra': []}

    if rule.notify_admins:
        from app.rbac.service import users_with_permission
        admins = users_with_permission('notifications.receive')
        breakdown['admins'] = [u.email for u in admins if u.email]

    if rule.notify_managers:
        managers = SiteSettings.get().event_manager_emails or []
        breakdown['managers'] = list(managers)

    if rule.notify_event_trainer and instance is not None:
        trainer = getattr(instance, 'effective_trainer', None)
        trainer_email = getattr(trainer, 'email', None) if trainer else None
        if trainer_email:
            breakdown['trainer'].append(trainer_email)

    breakdown['extra'] = list(rule.extra_emails or [])
    return rule, None, breakdown


def _dedup_preserve_order(raw_emails):
    seen = set()
    out = []
    for raw in raw_emails:
        norm = _normalize(raw)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def resolve(event_type, instance=None, new_status=None):
    """Повернути список email-ів, на які слід надіслати admin-нотифікацію
    для подіі event_type. Fail-soft: при будь-якій DB-помилці -- log + []."""
    try:
        _rule, skip_reason, breakdown = _resolve_sources(
            event_type, instance, new_status,
        )
    except Exception:
        logger.exception(
            'notification_recipients.resolve failed for event_type=%s', event_type,
        )
        return []

    if skip_reason:
        logger.info(
            'notification_recipients: skip event_type=%s reason=%s new_status=%s',
            event_type, skip_reason, new_status,
        )
        return []

    flat = (
        breakdown['admins']
        + breakdown['managers']
        + breakdown['trainer']
        + breakdown['extra']
    )
    out = _dedup_preserve_order(flat)
    if not out:
        logger.info(
            'notification_recipients: no recipients for event_type=%s '
            '(rule may be empty or all sources empty)',
            event_type,
        )
    return out


def preview(event_type, instance=None, new_status=None):
    """Як resolve, але повертає breakdown по джерелах -- для admin UI,
    щоб адмін бачив, КОГО саме охопить його налаштування."""
    try:
        rule, skip_reason, breakdown = _resolve_sources(
            event_type, instance, new_status,
        )
    except Exception:
        logger.exception(
            'notification_recipients.preview failed for event_type=%s', event_type,
        )
        return {
            'enabled': False,
            'skip_reason': 'resolve_error',
            'total': 0,
            'sources': {'admins': [], 'managers': [], 'trainer': [], 'extra': []},
        }

    # Per-source dedup для відображення (між джерелами дублі легітимні --
    # один email може потрапити з admins і з extra; показуємо обидва).
    sources = {
        key: _dedup_preserve_order(items) for key, items in breakdown.items()
    }
    flat = _dedup_preserve_order(
        sources['admins'] + sources['managers']
        + sources['trainer'] + sources['extra']
    )
    return {
        'enabled': rule.enabled,
        'skip_reason': skip_reason,
        'total': len(flat),
        'sources': sources,
        'unique_recipients': flat,
    }
