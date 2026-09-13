"""PostHog: додатковий проєкт (другий Project API Key).

Revision ID: posthog_secondary_20260913
Revises: quiz_invite_20260913

Двоє людей ведуть кожен свій проєкт PostHog зі своїми дашбордами, тож одні й
ті самі події мають іти в обидва. Другий ключ лише дублює збір -- аварійні
рубильники (posthog_enabled, posthog_session_recording) лишаються спільними.

Прапорець запису сесій тут ДВОСТАННИЙ, без env: другий записувач подвоює
навантаження на пристрій відвідувача, тож за замовчуванням він вимкнений, і
вмикати його -- лише свідоме рішення в адмінці.
"""
import sqlalchemy as sa
from alembic import op

revision = 'posthog_secondary_20260913'
down_revision = 'quiz_invite_20260913'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'posthog_secondary_api_key', sa.String(length=60),
            nullable=False, server_default=''))
        batch_op.add_column(sa.Column(
            'posthog_secondary_session_recording', sa.Boolean(),
            nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('posthog_secondary_session_recording')
        batch_op.drop_column('posthog_secondary_api_key')
