"""Certificate-data reminder: idempotency flag + configurable days

Revision ID: certdata_nag_20260708
Revises: roi_calc_20260708
Create Date: 2026-07-08 00:00:00.000000

Auto-email "заповніть дані для сертифіката" N днів до заходу для
учасників з незаповненою МОЗ-анкетою (замикає ланцюжок нагадувань:
header-індикатор, pop-up, банер, лист підтвердження). Email іде через
наявний тригер 'reminder' (opt-out поважається; CHECK не чіпаємо).

- event_registrations.certdata_reminder_sent_at -- ідемпотентність
  (один лист на реєстрацію);
- site_settings.certdata_reminder_days -- за скільки днів нагадувати
  (0 -- вимкнено), редагується в /admin/settings.
"""
from alembic import op
import sqlalchemy as sa


revision = 'certdata_nag_20260708'
down_revision = 'roi_calc_20260708'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('certdata_reminder_sent_at',
                                      sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('certdata_reminder_days', sa.Integer(),
                                      nullable=False, server_default='3'))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('certdata_reminder_days')
    with op.batch_alter_table('event_registrations', schema=None) as batch_op:
        batch_op.drop_column('certdata_reminder_sent_at')
