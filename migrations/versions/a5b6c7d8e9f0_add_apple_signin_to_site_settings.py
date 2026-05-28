"""Add Apple Sign In fields to site_settings

Phase 5 of auth unification. Apple Sign In вимагає 4 публічних
ідентифікатори + 1 приватний ключ:
  - apple_signin_enabled: master toggle.
  - apple_team_id: 10-символьний ID розробника з developer.apple.com.
  - apple_services_id: bundle ID для web (наприклад com.example.web).
  - apple_key_id: 10-символьний ID приватного ключа.
  - apple_private_key: вміст .p8 файлу (PEM, ~300 байт), Fernet-encrypted.

Backward-safe ADD COLUMN з server_default ''/false. Старий код продовжує
працювати.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-05-28 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a5b6c7d8e9f0'
down_revision = 'f4a5b6c7d8e9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('apple_signin_enabled', sa.Boolean(),
                      nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column('apple_team_id', sa.String(length=50),
                      nullable=True, server_default='')
        )
        batch_op.add_column(
            sa.Column('apple_services_id', sa.String(length=255),
                      nullable=True, server_default='')
        )
        batch_op.add_column(
            sa.Column('apple_key_id', sa.String(length=50),
                      nullable=True, server_default='')
        )
        batch_op.add_column(
            sa.Column('apple_private_key', sa.Text(),
                      nullable=True, server_default='')
        )


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('apple_private_key')
        batch_op.drop_column('apple_key_id')
        batch_op.drop_column('apple_services_id')
        batch_op.drop_column('apple_team_id')
        batch_op.drop_column('apple_signin_enabled')
