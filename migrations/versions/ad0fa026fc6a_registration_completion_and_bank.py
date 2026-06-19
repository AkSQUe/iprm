"""registration completion token + bank requisites in site_settings

Revision ID: ad0fa026fc6a
Revises: e1d2c3b4a5f6
Create Date: 2026-06-19

Альтернативний pipeline реєстрації: токен самостійного завершення на
event_registrations (+expires/used) і банківські реквізити у site_settings
для генерації рахунка на оплату.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ad0fa026fc6a'
down_revision = 'e1d2c3b4a5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('event_registrations', sa.Column('completion_token', sa.String(length=64), nullable=True))
    op.add_column('event_registrations', sa.Column('completion_token_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('event_registrations', sa.Column('completion_token_used_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_event_registrations_completion_token', 'event_registrations', ['completion_token'], unique=True)

    op.add_column('site_settings', sa.Column('bank_iban', sa.String(length=34), nullable=False, server_default='UA213052990000026003006239637'))
    op.add_column('site_settings', sa.Column('bank_name', sa.String(length=255), nullable=False, server_default='АТКБ «ПРИВАТБАНК»'))
    op.add_column('site_settings', sa.Column('tax_status', sa.String(length=255), nullable=False, server_default='Платник єдиного податку третьої групи (неплатник ПДВ)'))


def downgrade():
    op.drop_column('site_settings', 'tax_status')
    op.drop_column('site_settings', 'bank_name')
    op.drop_column('site_settings', 'bank_iban')
    op.drop_index('ix_event_registrations_completion_token', table_name='event_registrations')
    op.drop_column('event_registrations', 'completion_token_used_at')
    op.drop_column('event_registrations', 'completion_token_expires_at')
    op.drop_column('event_registrations', 'completion_token')
