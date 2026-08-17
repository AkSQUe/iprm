"""Налаштування інтеграції з Sintegrum

Revision ID: sintegrum_cfg_20260817
Revises: quiz_20260817
Create Date: 2026-08-17 14:10:00.000000

Sintegrum -- зовнішня LMS, де відбувається навчання на онлайн-курсах.
ІПРМ дзеркалить її каталог треків, продає доступ і видає учаснику
тимчасове посилання на навчання.

Ключ API зберігається в базі (вимога замовника) і шифрується Fernet --
тим самим механізмом, що partner_api_key і liqpay_private_key. У колонці
лежить шифротекст, тому 500 символів на 40-символьний ключ.

sintegrum_access_ttl_hours -- термін життя НАШОГО посилання на навчання.
Ціль редіректу (посилання реєстрації на боці Sintegrum) безстрокова.
"""
from alembic import op
import sqlalchemy as sa


revision = 'sintegrum_cfg_20260817'
down_revision = 'quiz_20260817'
branch_labels = None
depends_on = None


COLUMNS = (
    'sintegrum_enabled',
    'show_online_courses',
    'sintegrum_api_base_url',
    'sintegrum_company_alias',
    'sintegrum_api_key',
    'sintegrum_api_key_set_at',
    'sintegrum_sync_interval_minutes',
    'sintegrum_access_ttl_hours',
    'sintegrum_last_sync_at',
    'sintegrum_last_sync_status',
    'sintegrum_last_sync_error',
)


def upgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.add_column(sa.Column(
            'sintegrum_enabled', sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ))
        batch.add_column(sa.Column(
            'show_online_courses', sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ))
        batch.add_column(sa.Column(
            'sintegrum_api_base_url', sa.String(length=500), nullable=False,
            server_default='https://api.sintegrum.com',
        ))
        batch.add_column(sa.Column(
            'sintegrum_company_alias', sa.String(length=100), nullable=False,
            server_default='',
        ))
        batch.add_column(sa.Column(
            'sintegrum_api_key', sa.String(length=500), nullable=True,
            server_default='',
        ))
        batch.add_column(sa.Column(
            'sintegrum_api_key_set_at', sa.DateTime(timezone=True), nullable=True,
        ))
        batch.add_column(sa.Column(
            'sintegrum_sync_interval_minutes', sa.Integer(), nullable=False,
            server_default='60',
        ))
        batch.add_column(sa.Column(
            'sintegrum_access_ttl_hours', sa.Integer(), nullable=False,
            server_default='72',
        ))
        batch.add_column(sa.Column(
            'sintegrum_last_sync_at', sa.DateTime(timezone=True), nullable=True,
        ))
        batch.add_column(sa.Column(
            'sintegrum_last_sync_status', sa.String(length=20), nullable=True,
            server_default='',
        ))
        batch.add_column(sa.Column(
            'sintegrum_last_sync_error', sa.Text(), nullable=True,
            server_default='',
        ))


def downgrade():
    # Відкат стирає збережений ключ API -- відновити його можна лише
    # повторним введенням в адмінці. Інших наслідків немає: таблиці
    # каталогу створюються наступними міграціями.
    with op.batch_alter_table('site_settings') as batch:
        for column in reversed(COLUMNS):
            batch.drop_column(column)
