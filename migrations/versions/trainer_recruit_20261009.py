"""Залучення тренерів: заявки кандидатів, тексти запрошення, тип листа.

* таблиця trainer_applications;
* 6 колонок site_settings із текстами запрошення (порожнє = дефолт із коду);
* 'trainer_application' у CHECK ck_email_logs_trigger (той самий перелік, що
  в EmailLog.__table_args__ і EmailLog.TRIGGERS) і в
  ck_notification_rules_event_type;
* рядок правила одержувачів: адмінам -- ні, лише додаткова адреса. Адреси
  Дмитра Бараша в репозиторії немає, тож туди лягає email сайту, а якщо й
  його немає -- лист іде адмінам, щоб заявки не губились. Змінюється на
  /admin/notifications/recipients.

Revision ID: trainer_recruit_20261009
Revises: paid_at_precision_20261008
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = 'trainer_recruit_20261009'
down_revision = 'paid_at_precision_20261008'
branch_labels = None
depends_on = None

_TRIGGERS_OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'material_request', 'trainer_presentation', 'test')"
)
_TRIGGERS_NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'material_request', 'trainer_presentation', "
    "'trainer_application', 'test')"
)
_TYPES_OLD = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials', 'meta_lead', 'certificate', "
              "'material_request')")
_TYPES_NEW = ("event_type IN ('registration', 'payment', 'course_request', "
              "'status_change', 'materials', 'meta_lead', 'certificate', "
              "'material_request', 'trainer_application')")

_TEXT_COLUMNS = (
    'recruit_teaser_title', 'recruit_teaser_text', 'recruit_page_title',
    'recruit_page_intro', 'recruit_page_benefits', 'recruit_page_closing',
)


def upgrade():
    op.create_table(
        'trainer_applications',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('city', sa.String(length=120), nullable=True),
        sa.Column('specialty', sa.String(length=255), nullable=False),
        sa.Column('workplace', sa.Text(), nullable=True),
        sa.Column('social_links', sa.Text(), nullable=True),
        sa.Column('topic', sa.Text(), nullable=False),
        sa.Column('answers', sa.JSON(), nullable=False),
        sa.Column('locale', sa.String(length=5), nullable=False, server_default='uk'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='new'),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('trainer_id', sa.BigInteger(),
                  sa.ForeignKey('trainers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('new', 'in_progress', 'approved', 'rejected')",
            name='ck_trainer_applications_status',
        ),
    )
    op.create_index('ix_trainer_applications_email', 'trainer_applications', ['email'])
    op.create_index('ix_trainer_applications_status', 'trainer_applications', ['status'])
    op.create_index('ix_trainer_applications_created_at', 'trainer_applications',
                    ['created_at'])

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        for name in _TEXT_COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Text(), nullable=False,
                                          server_default=''))

    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', _TRIGGERS_NEW)

    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_NEW)

    bind = op.get_bind()
    site_email = bind.execute(sa.text('SELECT email FROM site_settings WHERE id = 1')).scalar()
    site_email = (site_email or '').strip().lower()
    rules = sa.table(
        'notification_rules',
        sa.column('event_type', sa.String), sa.column('enabled', sa.Boolean),
        sa.column('notify_admins', sa.Boolean), sa.column('notify_managers', sa.Boolean),
        sa.column('notify_event_trainer', sa.Boolean), sa.column('extra_emails', sa.JSON),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
    )
    op.bulk_insert(rules, [{
        'event_type': 'trainer_application', 'enabled': True,
        'notify_admins': not site_email, 'notify_managers': False,
        'notify_event_trainer': False,
        'extra_emails': [site_email] if site_email else [],
        'created_at': datetime.now(timezone.utc), 'updated_at': datetime.now(timezone.utc),
    }])


def downgrade():
    op.execute("DELETE FROM notification_rules WHERE event_type = 'trainer_application'")
    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _TYPES_OLD)

    op.execute("DELETE FROM email_logs WHERE trigger = 'trainer_application'")
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', _TRIGGERS_OLD)

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        for name in reversed(_TEXT_COLUMNS):
            batch_op.drop_column(name)

    op.drop_index('ix_trainer_applications_created_at', table_name='trainer_applications')
    op.drop_index('ix_trainer_applications_status', table_name='trainer_applications')
    op.drop_index('ix_trainer_applications_email', table_name='trainer_applications')
    op.drop_table('trainer_applications')
