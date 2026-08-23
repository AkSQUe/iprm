"""PostHog: тристанні прапорці + виняток для адмінки.

Revision ID: posthog_flags_20260823
Revises: posthog_20260823

Прапорці стають NULLABLE, і NULL значить "в адмінці не задано, вирішує env".

Навіщо: доти прапорець БД дивився на наявність ключа В БД і через це мовчки
ігнорувався на проді, де ключ приходить з env. Адміністратор знімав галку
"Увімкнути аналітику", бачив "Збережено" -- і збір даних тривав. На сайті з
медданими це зламаний аварійний рубильник, а не косметика.

UPDATE ... SET NULL наприкінці обов'язковий. Колонки створювались із
server_default=false, тож у наявному рядку лежить явне False. Якби воно
лишилось, після міграції воно почало б ПЕРЕКРИВАТИ env -- і трекінг, який
зараз працює зі змінних оточення, вимкнувся б сам собою. NULL зберігає
поточну поведінку: рішення й далі за env, доки адмін не тикне галку свідомо.
"""
import sqlalchemy as sa
from alembic import op

revision = 'posthog_flags_20260823'
down_revision = 'posthog_20260823'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.alter_column(
            'posthog_enabled',
            existing_type=sa.Boolean(),
            nullable=True,
            server_default=None,
        )
        batch_op.alter_column(
            'posthog_session_recording',
            existing_type=sa.Boolean(),
            nullable=True,
            server_default=None,
        )
        batch_op.add_column(sa.Column(
            'posthog_exclude_admin', sa.Boolean(), nullable=True))

    op.execute(
        'UPDATE site_settings SET posthog_enabled = NULL, '
        'posthog_session_recording = NULL'
    )


def downgrade():
    # Назад у NOT NULL: NULL означав "вирішує env", і найближчий до нього
    # аналог у двостанній схемі -- false (не задано в адмінці).
    op.execute(
        'UPDATE site_settings SET posthog_enabled = COALESCE(posthog_enabled, false), '
        'posthog_session_recording = COALESCE(posthog_session_recording, false)'
    )
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('posthog_exclude_admin')
        batch_op.alter_column(
            'posthog_session_recording',
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        )
        batch_op.alter_column(
            'posthog_enabled',
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        )
