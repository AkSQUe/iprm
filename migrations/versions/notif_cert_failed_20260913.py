"""Notification rules: allow 'certificate' event type in CHECK

Revision ID: notif_cert_failed_20260913
Revises: merge_trainers_main_20260912
Create Date: 2026-09-13 00:00:00.000000

Нова admin-нотифікація: учасник склав тест, а сертифікат автоматично не
видався. CHECK ck_notification_rules_event_type генерується з
NotificationRule.EVENT_TYPES, тож без цієї міграції сторінка
«Сповіщення -> Одержувачі» падала б на вставці рядка правила (та сама
пастка, що notif_materials_20260708).
"""
from alembic import op


revision = 'notif_cert_failed_20260913'
down_revision = 'merge_trainers_main_20260912'
branch_labels = None
depends_on = None

_TYPES_OLD = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials', 'meta_lead')")
_TYPES_NEW = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials', 'meta_lead', 'certificate')")


def upgrade():
    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_NEW)


def downgrade():
    # Перед звуженням CHECK прибираємо рядок 'certificate', інакше constraint
    # не створиться.
    op.execute("DELETE FROM notification_rules WHERE event_type = 'certificate'")
    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_OLD)
