"""Нагадування про невикористаний доступ до онлайн-курсу.

Дві колонки: позначка надісланого листа на самому замовленні (той самий
підхід, що в `registrations.certdata_reminder_sent_at` -- один лист на
замовлення, без сканування журналу пошти) і період у налаштуваннях, щоб
адмін міг його змінити чи вимкнути нулем без деплою.

Revision ID: online_reminder_20260819
Revises: meta_leads_20260819
"""
import sqlalchemy as sa
from alembic import op

revision = 'online_reminder_20260819'
down_revision = 'meta_leads_20260819'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('online_enrollments') as batch:
        batch.add_column(
            sa.Column('access_reminder_sent_at', sa.DateTime(timezone=True),
                      nullable=True))

    with op.batch_alter_table('site_settings') as batch:
        batch.add_column(
            sa.Column('sintegrum_access_reminder_days', sa.Integer(),
                      nullable=False, server_default='3'))


def downgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.drop_column('sintegrum_access_reminder_days')

    with op.batch_alter_table('online_enrollments') as batch:
        batch.drop_column('access_reminder_sent_at')
