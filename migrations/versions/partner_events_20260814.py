"""Черга доставок несе не лише каталог: партнерські події з власним часом

Revision ID: partner_events_20260814
Revises: mm_req_lifecycle_20260813
Create Date: 2026-08-14

Why
---
Досі назовні йшов лише каталог курсів: рядок у ``webhook_deliveries`` завжди
означав «перечитай курс». Тепер партнеру треба знати ще й ФАКТИ — хто
зареєструвався, хто оплатив, кому ми надіслали лист. Це інший клас події:
каталожну можна повторити скільки завгодно й нічого не зіпсувати, а
повторно порахована реєстрація псує статистику назавжди.

Друга черга для них була б помилкою: ретраї, exponential backoff, circuit
breaker і видимість в адмінці вже написані для цієї таблиці, і копія
розійшлася б із оригіналом на першій же правці.

``course_id``/``course_slug``/``action`` стають nullable: у події
«надіслали лист» курсу немає взагалі. CHECK на ``action`` послаблено до
«NULL або одне з трьох», і додано інваріант «рядок мусить бути або
каталожним, або подією» — інакше в чергу пролізе запис, який диспетчер не
вміє відправити, і він мовчки крутитиметься до вичерпання спроб.

Даних міграція не чіпає: наявні рядки лишаються каталожними
(``event_type IS NULL``).
"""
from alembic import op
import sqlalchemy as sa


revision = 'partner_events_20260814'
down_revision = 'mm_req_lifecycle_20260813'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('webhook_deliveries',
                  sa.Column('event_type', sa.String(length=60), nullable=True))
    op.add_column('webhook_deliveries',
                  sa.Column('payload', sa.JSON(), nullable=True))
    op.create_index('ix_webhook_deliveries_event_type', 'webhook_deliveries',
                    ['event_type'])

    op.alter_column('webhook_deliveries', 'course_id', nullable=True,
                    existing_type=sa.BigInteger())
    op.alter_column('webhook_deliveries', 'course_slug', nullable=True,
                    existing_type=sa.String(length=200))
    op.alter_column('webhook_deliveries', 'action', nullable=True,
                    existing_type=sa.String(length=20))

    op.drop_constraint('ck_webhook_deliveries_action', 'webhook_deliveries',
                       type_='check')
    op.create_check_constraint(
        'ck_webhook_deliveries_action', 'webhook_deliveries',
        "action IS NULL OR action IN ('created', 'updated', 'deleted')",
    )
    op.create_check_constraint(
        'ck_webhook_deliveries_kind', 'webhook_deliveries',
        'event_type IS NOT NULL OR course_id IS NOT NULL',
    )


def downgrade():
    # Партнерські події зникають разом із колонками; повернути NOT NULL можна
    # лише прибравши рядки, у яких курсу не було.
    op.execute('DELETE FROM webhook_deliveries WHERE event_type IS NOT NULL')

    op.drop_constraint('ck_webhook_deliveries_kind', 'webhook_deliveries',
                       type_='check')
    op.drop_constraint('ck_webhook_deliveries_action', 'webhook_deliveries',
                       type_='check')
    op.create_check_constraint(
        'ck_webhook_deliveries_action', 'webhook_deliveries',
        "action IN ('created', 'updated', 'deleted')",
    )

    op.alter_column('webhook_deliveries', 'action', nullable=False,
                    existing_type=sa.String(length=20))
    op.alter_column('webhook_deliveries', 'course_slug', nullable=False,
                    existing_type=sa.String(length=200))
    op.alter_column('webhook_deliveries', 'course_id', nullable=False,
                    existing_type=sa.BigInteger())

    op.drop_index('ix_webhook_deliveries_event_type',
                  table_name='webhook_deliveries')
    op.drop_column('webhook_deliveries', 'payload')
    op.drop_column('webhook_deliveries', 'event_type')
