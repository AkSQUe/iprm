"""Часткові повернення коштів: сума, дата й підстава повернення.

До цієї міграції повернення було операцією «все або нічого»: система
знала лише payment_status='refunded'. Політика повернення (§4.1) вимагає
50% і 25%, тож потрібне місце, куди записати СКІЛЬКИ повернуто -- інакше
часткове повернення неможливо ані провести, ані звірити.

`refunded_amount` накопичувальна: повернень за одне замовлення може бути
кілька (спершу 50% за політикою, потім решта за рішенням керівництва).
NOT NULL DEFAULT 0, щоб код ніколи не порівнював None із сумою.

Журнал payment_transactions свідомо не чіпаємо: часткове повернення
пишеться туди рядком source='refund' з amount, а mapped_status лишається
'paid'. Це зберігає CHECK ck_payment_transactions_mapped_status без змін
і не ламає наявні звіти, які читають цей стовпець.

Revision ID: refunds_20260819
Revises: online_guest_20260817
"""
import sqlalchemy as sa
from alembic import op

revision = 'refunds_20260819'
down_revision = 'online_guest_20260817'
branch_labels = None
depends_on = None

TABLES = ('event_registrations', 'online_enrollments')


def upgrade():
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(
                'refunded_amount', sa.Numeric(10, 2),
                nullable=False, server_default='0',
            ))
            batch.add_column(sa.Column(
                'refunded_at', sa.DateTime(timezone=True), nullable=True,
            ))
            batch.add_column(sa.Column(
                'refund_reason', sa.String(500), nullable=True,
            ))

    # Історичні рядки: те, що вже позначене як повернене, повернене
    # повністю -- інших повернень система робити не вміла. Без цього
    # бекфілу старі повернення виглядали б як «повернено 0 грн», і
    # перевірка залишку дозволила б повернути гроші вдруге.
    for table in TABLES:
        op.execute(sa.text(
            f'UPDATE {table} SET refunded_amount = COALESCE(payment_amount, 0), '
            f'refunded_at = COALESCE(paid_at, created_at) '
            f"WHERE payment_status = 'refunded'"
        ))

    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(
                f'ck_{table}_refunded_amount_non_negative',
                'refunded_amount >= 0',
            )


def downgrade():
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(
                f'ck_{table}_refunded_amount_non_negative', type_='check')
            batch.drop_column('refund_reason')
            batch.drop_column('refunded_at')
            batch.drop_column('refunded_amount')
