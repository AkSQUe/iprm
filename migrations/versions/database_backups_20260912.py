"""Реєстр резервних копій БД: таблиця database_backups

Revision ID: database_backups_20260912
Revises: partner_identity_20260912
Create Date: 2026-09-12 10:00:00.000000

Модель DatabaseBackup і вся система бекапів існують із 12.06.2026
(коміт dfed3c75), але файлу міграції до них не було. У dev-базі таблицю
колись створили вручну, тому локально нічого не падало, а на проді її не
було взагалі: сторінка /admin/backups віддавала 500, а обидві щоденні
джоби (автокопія о 3:00 і очищення о 4:00) щоночі падали на
`relation "database_backups" does not exist` -- 490 рядків у журналі за
два тижні. Бази не бекапило три місяці.

Структура точно за моделлю, включно з трьома CHECK-обмеженнями. Індекс
на (status, created_at) -- під запити, якими живе сторінка: статистика
шукає останню успішну копію, очищення відбирає завершені старші за
retention.
"""
from alembic import op
import sqlalchemy as sa


revision = 'database_backups_20260912'
down_revision = 'partner_identity_20260912'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'database_backups',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                  nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('backup_type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('compression', sa.String(length=10), nullable=True),
        sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('pg_dump_version', sa.String(length=50), nullable=True),
        sa.Column('db_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'],
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "backup_type IN ('full', 'schema_only', 'data_only', 'pre_restore')",
            name='ck_database_backups_type',
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed', 'failed', 'corrupted')",
            name='ck_database_backups_status',
        ),
        sa.CheckConstraint('file_size_bytes >= 0',
                           name='ck_database_backups_size_non_negative'),
    )
    with op.batch_alter_table('database_backups', schema=None) as batch_op:
        batch_op.create_index('ix_database_backups_status_created',
                              ['status', 'created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('database_backups', schema=None) as batch_op:
        batch_op.drop_index('ix_database_backups_status_created')
    op.drop_table('database_backups')
