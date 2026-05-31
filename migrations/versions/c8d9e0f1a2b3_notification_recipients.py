"""Add notification_rules + site_settings.event_manager_emails

Recipient routing for admin-side event notifications. До цієї міграції
тільки send_course_request_notification мав admin-нотифікацію з
хардкод-логікою (SiteSettings.email OR User.is_admin). Тепер:

  - notification_rules: рядок на event_type з прапорами та extra_emails
  - site_settings.event_manager_emails: глобальний пул менеджерських
    email-ів, на який посилається прапор notify_managers

Seed: створюємо 4 рядки (registration, payment, course_request,
status_change) з default-ами (enabled=True, notify_admins=True, інші
False, extra_emails=[]). Адмін потім налаштовує через
/admin/notifications/recipients.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-05-31 18:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c8d9e0f1a2b3'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notification_rules',
        sa.Column('event_type', sa.String(length=40), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notify_admins', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notify_managers', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('notify_event_trainer', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('extra_emails', sa.JSON(), nullable=False, server_default='[]'),
        # Для status_change: список статусів, при переході на які шлемо
        # admin-нотифікацію. Порожній/null -> дефолт ['cancelled'].
        # Для інших event_type ігнорується.
        sa.Column('trigger_statuses', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.CheckConstraint(
            "event_type IN ('registration', 'payment', 'course_request', 'status_change')",
            name='ck_notification_rules_event_type',
        ),
    )

    # Seed 4 події з безпечними дефолтами. bulk_insert уникає dialect-
    # специфічного синтаксису ('::json' для PG / "json('[]')" для SQLite) --
    # SQLAlchemy сам серіалізує JSON-колонку через відповідний type adapter.
    seed_table = sa.table(
        'notification_rules',
        sa.column('event_type', sa.String),
        sa.column('enabled', sa.Boolean),
        sa.column('notify_admins', sa.Boolean),
        sa.column('notify_managers', sa.Boolean),
        sa.column('notify_event_trainer', sa.Boolean),
        sa.column('extra_emails', sa.JSON),
        sa.column('trigger_statuses', sa.JSON),
    )
    op.bulk_insert(seed_table, [
        {'event_type': 'registration', 'enabled': True, 'notify_admins': True,
         'notify_managers': False, 'notify_event_trainer': False,
         'extra_emails': [], 'trigger_statuses': None},
        {'event_type': 'payment', 'enabled': True, 'notify_admins': True,
         'notify_managers': False, 'notify_event_trainer': False,
         'extra_emails': [], 'trigger_statuses': None},
        {'event_type': 'course_request', 'enabled': True, 'notify_admins': True,
         'notify_managers': False, 'notify_event_trainer': False,
         'extra_emails': [], 'trigger_statuses': None},
        # Для status_change за замовчуванням -- лише скасування.
        {'event_type': 'status_change', 'enabled': True, 'notify_admins': True,
         'notify_managers': False, 'notify_event_trainer': False,
         'extra_emails': [], 'trigger_statuses': ['cancelled']},
    ])

    op.add_column(
        'site_settings',
        sa.Column(
            'event_manager_emails', sa.JSON(),
            nullable=False, server_default='[]',
        ),
    )

    # Trainer email -- для notify_event_trainer (історично trainers
    # додавалися без контактної пошти).
    op.add_column(
        'trainers',
        sa.Column('email', sa.String(length=255), nullable=True),
    )


def downgrade():
    op.drop_column('trainers', 'email')
    op.drop_column('site_settings', 'event_manager_emails')
    op.drop_table('notification_rules')
