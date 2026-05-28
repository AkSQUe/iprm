"""Add reCAPTCHA v3 fields to site_settings

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-28 13:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('recaptcha_enabled', sa.Boolean(),
                      nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column('recaptcha_site_key', sa.String(length=255),
                      nullable=True, server_default='')
        )
        batch_op.add_column(
            sa.Column('recaptcha_secret_key', sa.String(length=500),
                      nullable=True, server_default='')
        )
        batch_op.add_column(
            sa.Column('recaptcha_score_threshold', sa.Float(),
                      nullable=False, server_default='0.5')
        )


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('recaptcha_score_threshold')
        batch_op.drop_column('recaptcha_secret_key')
        batch_op.drop_column('recaptcha_site_key')
        batch_op.drop_column('recaptcha_enabled')
