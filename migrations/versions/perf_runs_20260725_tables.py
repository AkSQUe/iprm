"""Perf runs: заміри швидкості сторінок + ключ приймання

Revision ID: perf_runs_20260725
Revises: home_hero_video_20260725
Create Date: 2026-07-25 00:00:00.000000

Створює perf_runs / perf_page_metrics -- історію замірів від
tools/perf/perf_check.py (перегляд у /admin/perf), і додає
site_settings.perf_api_key для автентифікації приймання.

Заміри свідомо виконуються ПОЗА продом (1 ядро, 2 ГБ без swap), тому таблиці
лише зберігають надіслане ззовні -- фонових задач ця міграція не додає.
"""
from alembic import op
import sqlalchemy as sa


revision = 'perf_runs_20260725'
down_revision = 'home_hero_video_20260725'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'perf_runs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('measured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('base_url', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('source', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('note', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('runs_per_page', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tool_version', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('verdict', sa.String(length=10), nullable=False, server_default='OK'),
        sa.Column('pages_total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pages_warn', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pages_fail', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('budgets', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("verdict IN ('OK', 'WARN', 'FAIL')", name='ck_perf_runs_verdict'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_perf_runs_measured_at', 'perf_runs', ['measured_at'])

    op.create_table(
        'perf_page_metrics',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.BigInteger(), nullable=False),
        sa.Column('profile', sa.String(length=20), nullable=False),
        sa.Column('path', sa.String(length=255), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('status', sa.Integer(), nullable=True),
        sa.Column('ttfb', sa.Integer(), nullable=True),
        sa.Column('fcp', sa.Integer(), nullable=True),
        sa.Column('lcp', sa.Integer(), nullable=True),
        sa.Column('tbt', sa.Integer(), nullable=True),
        sa.Column('load_ms', sa.Integer(), nullable=True),
        sa.Column('cls', sa.Float(), nullable=True),
        sa.Column('total_transfer', sa.BigInteger(), nullable=True, server_default='0'),
        sa.Column('req_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('doc_transfer', sa.BigInteger(), nullable=True, server_default='0'),
        sa.Column('doc_decoded', sa.BigInteger(), nullable=True, server_default='0'),
        sa.Column('verdict', sa.String(length=10), nullable=False, server_default='OK'),
        sa.Column('budget', sa.JSON(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('error', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "verdict IN ('OK', 'WARN', 'FAIL')", name='ck_perf_page_metrics_verdict',
        ),
        sa.ForeignKeyConstraint(['run_id'], ['perf_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_perf_page_metrics_run_id', 'perf_page_metrics', ['run_id'])
    op.create_index(
        'ix_perf_page_metrics_profile_path', 'perf_page_metrics', ['profile', 'path'],
    )

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('perf_api_key', sa.String(length=500),
                                      nullable=True, server_default=''))
        batch_op.add_column(sa.Column('perf_api_key_set_at', sa.DateTime(timezone=True),
                                      nullable=True))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('perf_api_key_set_at')
        batch_op.drop_column('perf_api_key')

    op.drop_index('ix_perf_page_metrics_profile_path', table_name='perf_page_metrics')
    op.drop_index('ix_perf_page_metrics_run_id', table_name='perf_page_metrics')
    op.drop_table('perf_page_metrics')
    op.drop_index('ix_perf_runs_measured_at', table_name='perf_runs')
    op.drop_table('perf_runs')
