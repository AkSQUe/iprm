"""Дата скасування реєстрації й онлайн-курсу (cancelled_at).

Фінзвіт відносить утриману частину скасованої оплати до виручки на дату
повернення, а без повернення -- на дату скасування (рішення власника
10.10.2026). Статус моменту скасування не зберігав.

Наповнення для вже скасованих -- найкращою відомою оцінкою, у такому
порядку:

* `refunded_at` -- повне повернення саме й переводить у «скасовано»
  (payment_ops), тож для таких дата точна;
* `decided_at` задоволеної заявки на повернення -- рішення про відмову;
* `updated_at` -- остання правка рядка; для скасованих вручну це верхня
  межа: справжнє скасування могло бути раніше, пізніше -- ні.

Нові скасування дату отримують слухачем у CancellableMixin.

Revision ID: cancelled_at_20261010
Revises: drop_cert_global_ctr_20261009
"""
import sqlalchemy as sa
from alembic import op

revision = 'cancelled_at_20261010'
down_revision = 'drop_cert_global_ctr_20261009'
branch_labels = None
depends_on = None

_TABLES = (
    ('event_registrations', 'registration_id'),
    ('online_enrollments', 'enrollment_id'),
)


def upgrade():
    for table, request_fk in _TABLES:
        op.add_column(table, sa.Column(
            'cancelled_at', sa.DateTime(timezone=True), nullable=True))
        op.execute(sa.text(f"""
            UPDATE {table} SET cancelled_at = COALESCE(
                refunded_at,
                (SELECT MAX(q.decided_at) FROM refund_requests q
                  WHERE q.{request_fk} = {table}.id AND q.status = 'approved'),
                updated_at,
                created_at
            )
            WHERE status = 'cancelled' AND cancelled_at IS NULL
        """))


def downgrade():
    for table, _fk in _TABLES:
        op.drop_column(table, 'cancelled_at')
