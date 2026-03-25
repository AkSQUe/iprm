"""Add CHECK constraints and index to email_logs and email_settings

Revision ID: bbfd90f9e6c3
Revises: 50ec7628e05e
Create Date: 2026-03-25 20:09:00.668852

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bbfd90f9e6c3'
down_revision = '50ec7628e05e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.create_index('ix_email_logs_created_at', ['created_at'], unique=False)
        batch_op.create_check_constraint(
            'ck_email_logs_status',
            "status IN ('pending', 'sent', 'failed')",
        )
        batch_op.create_check_constraint(
            'ck_email_logs_trigger',
            "trigger IN ('registration', 'payment', 'reminder', 'status_change', 'test')",
        )

    with op.batch_alter_table('email_settings', schema=None) as batch_op:
        batch_op.alter_column('smtp_password',
               existing_type=sa.VARCHAR(length=255),
               type_=sa.String(length=500),
               existing_nullable=True)
        batch_op.create_check_constraint(
            'ck_email_settings_port', 'smtp_port > 0',
        )


def downgrade():
    with op.batch_alter_table('email_settings', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_settings_port', type_='check')
        batch_op.alter_column('smtp_password',
               existing_type=sa.String(length=500),
               type_=sa.VARCHAR(length=255),
               existing_nullable=True)

    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.drop_constraint('ck_email_logs_status', type_='check')
        batch_op.drop_index('ix_email_logs_created_at')
