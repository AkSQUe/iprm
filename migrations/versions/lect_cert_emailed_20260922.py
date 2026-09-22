"""Колонка emailed_at у lecturer_certificates.

Стан «видано, лист ще не пішов». Наявні рядки позначаються опрацьованими
(emailed_at = issued_at): інакше перший тік джоби розсилки надіслав би листи
за всі минулі заходи. Позначка явна і не залежить від дати деплою.

Revision ID: lect_cert_emailed_20260922
Revises: email_trainer_reqs_20260919
"""
import sqlalchemy as sa
from alembic import op

revision = 'lect_cert_emailed_20260922'
down_revision = 'email_trainer_reqs_20260919'
branch_labels = None
depends_on = None

BACKFILL_SQL = 'UPDATE lecturer_certificates SET emailed_at = issued_at'


def upgrade():
    with op.batch_alter_table('lecturer_certificates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('emailed_at', sa.DateTime(timezone=True)))
        batch_op.create_index(
            'ix_lecturer_certificates_emailed_at', ['emailed_at'])
    op.execute(BACKFILL_SQL)


def downgrade():
    with op.batch_alter_table('lecturer_certificates', schema=None) as batch_op:
        batch_op.drop_index('ix_lecturer_certificates_emailed_at')
        batch_op.drop_column('emailed_at')
