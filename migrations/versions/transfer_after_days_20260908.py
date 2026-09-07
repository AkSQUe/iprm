"""Вікно пересадки після заходу

Revision ID: transfer_after_days_20260908
Revises: pay_methods_20260907
Create Date: 2026-09-08 00:00:00.000000

site_settings.transfer_after_days: скільки діб після заходу ще можна
пересадити учасника, який не прийшов. Доти будь-який минулий захід
блокувався запобіжником, писаним під вікно ПЕРЕД заходом.

server_default = '90' -- три місяці. Значення робоче, а не нейтральне:
фіча має працювати одразу після деплою, а не чекати, поки хтось відкриє
налаштування. 0 повертає колишню поведінку (після заходу -- ніколи).
"""
from alembic import op
import sqlalchemy as sa


revision = 'transfer_after_days_20260908'
down_revision = 'pay_methods_20260907'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.add_column(sa.Column(
            'transfer_after_days', sa.Integer(), nullable=False,
            server_default='90',
        ))


def downgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.drop_column('transfer_after_days')
