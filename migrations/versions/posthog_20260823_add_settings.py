"""PostHog: ключ проєкту + два прапорці на site_settings.

Revision ID: posthog_20260823
Revises: trainer_confirm_20260820

Прапорців два: posthog_enabled гасить усю аналітику, posthog_session_recording
-- саме запис екрана. Розділені навмисно (див. app/models/site_settings.py).

Усі три колонки NOT NULL із server_default: таблиця однорядкова, але
server_default тут не косметика -- без нього ALTER на наявному рядку впав би
на NOT NULL. Дефолти "вимкнено" і порожній ключ означають, що після міграції
трекінг НЕ вмикається сам собою: ключ вставляється в адмінці або приходить
з env-fallback.
"""
import sqlalchemy as sa
from alembic import op

revision = 'posthog_20260823'
down_revision = 'trainer_confirm_20260820'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'posthog_enabled', sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ))
        batch_op.add_column(sa.Column(
            'posthog_project_api_key', sa.String(length=60),
            nullable=False, server_default='',
        ))
        batch_op.add_column(sa.Column(
            'posthog_session_recording', sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('posthog_session_recording')
        batch_op.drop_column('posthog_project_api_key')
        batch_op.drop_column('posthog_enabled')
