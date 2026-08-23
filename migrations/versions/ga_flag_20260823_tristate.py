"""Google Analytics: тристанний прапорець (аварійний рубильник).

Revision ID: ga_flag_20260823
Revises: posthog_flags_20260823

Той самий дефект, який уже полагоджено для PostHog (posthog_flags_20260823),
але для GA він лишався: вимикача не було взагалі. Єдиним важелем в адмінці
було поле Measurement ID, а `effective_google_analytics_id` при порожньому
полі падала в env-fallback -- де в ProductionConfig вшитий реальний
`G-T2LHJ436ZG`. Адміністратор стирав ID, бачив "Збережено" і далі слав дані
в Google.

NULL значить "в адмінці не задано, вирішує env". Колонка створюється без
server_default саме заради цього: у наявному рядку опиниться NULL, тож
поведінка після міграції не змінюється ані на йоту -- GA лишається таким,
яким його зробили змінні оточення, доки адмін свідомо не тикне галку.
"""
import sqlalchemy as sa
from alembic import op

revision = 'ga_flag_20260823'
down_revision = 'posthog_flags_20260823'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'google_analytics_enabled', sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('google_analytics_enabled')
