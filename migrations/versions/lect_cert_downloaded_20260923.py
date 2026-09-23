"""Колонка downloaded_at у lecturer_certificates.

Коли тренер уперше завантажив PDF сертифіката в кабінеті. NULL -- документ
для нього ще «новий», і на картці «Сертифікати» стоїть позначка. Наявним
рядкам ставимо downloaded_at = issued_at: вони видані до появи позначки, і
без цього в кожного тренера одразу засвітилися б «нові» документи за всі
минулі заходи.

Revision ID: lect_cert_downloaded_20260923
Revises: email_attachments_20260923
"""
import sqlalchemy as sa
from alembic import op

revision = 'lect_cert_downloaded_20260923'
down_revision = 'email_attachments_20260923'
branch_labels = None
depends_on = None

BACKFILL_SQL = 'UPDATE lecturer_certificates SET downloaded_at = issued_at'


def upgrade():
    with op.batch_alter_table('lecturer_certificates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('downloaded_at', sa.DateTime(timezone=True)))
    op.execute(BACKFILL_SQL)


def downgrade():
    with op.batch_alter_table('lecturer_certificates', schema=None) as batch_op:
        batch_op.drop_column('downloaded_at')
