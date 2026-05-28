"""Add Google OAuth fields to site_settings

Phase 3 of auth unification. Додає три колонки для конфігурації Google
OAuth 2.0 sign-in:
  - google_oauth_enabled: master toggle (default false).
  - google_oauth_client_id: публічний client ID з GCP (видно у redirect-
    URI; не шифруємо).
  - google_oauth_client_secret: Fernet-зашифрований секрет.

Backward-safe ADD COLUMN з server_default. Старий код, що не знає про
GA OAuth, продовжує працювати; нові admin-сторінки і /auth/google/*
почнуть використовувати ці колонки після Phase 3 деплою.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-05-28 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('google_oauth_enabled', sa.Boolean(),
                      nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column('google_oauth_client_id', sa.String(length=255),
                      nullable=True, server_default='')
        )
        batch_op.add_column(
            sa.Column('google_oauth_client_secret', sa.String(length=500),
                      nullable=True, server_default='')
        )


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('google_oauth_client_secret')
        batch_op.drop_column('google_oauth_client_id')
        batch_op.drop_column('google_oauth_enabled')
