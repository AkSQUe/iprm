"""Поріг перенесення реєстрації як налаштування

Revision ID: transfer_min_days_20260907
Revises: rbac_20260905
Create Date: 2026-09-07 00:00:00.000000

site_settings.transfer_min_days: за скільки діб до заходу перенесення вже
неможливе. Доти число жило константою TRANSFER_MIN_HOURS = 48 у
app/services/transfer_service.py, і змінити його могла лише правка коду.

server_default = '2' -- рівно те, що робила константа, тож наявні рядки
після міграції поводяться як досі.
"""
from alembic import op
import sqlalchemy as sa


revision = 'transfer_min_days_20260907'
down_revision = 'rbac_20260905'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.add_column(sa.Column(
            'transfer_min_days', sa.Integer(), nullable=False,
            server_default='2',
        ))


def downgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.drop_column('transfer_min_days')
