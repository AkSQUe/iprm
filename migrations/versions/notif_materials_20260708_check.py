"""Notification rules: allow 'materials' event type in CHECK

Revision ID: notif_materials_20260708
Revises: course_tariffs_20260708
Create Date: 2026-07-08 00:00:00.000000

Fixes prod 500 on /admin/notifications/recipients (error #4996): the
materials-reservation feature (07.07) added 'materials' to
NotificationRule.EVENT_TYPES, but ck_notification_rules_event_type was
never extended, so the page's ensure-rows insert violated the constraint.
Same trap as email_logs.trigger; the model now derives the CHECK from
EVENT_TYPES to keep them in sync.
"""
from alembic import op


revision = 'notif_materials_20260708'
down_revision = 'course_tariffs_20260708'
branch_labels = None
depends_on = None

_TYPES_OLD = "event_type IN ('registration', 'payment', 'course_request', 'status_change')"
_TYPES_NEW = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials')")


def upgrade():
    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_NEW)


def downgrade():
    # Перед звуженням CHECK прибираємо рядок 'materials', інакше constraint
    # не створиться.
    op.execute("DELETE FROM notification_rules WHERE event_type = 'materials'")
    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_OLD)
