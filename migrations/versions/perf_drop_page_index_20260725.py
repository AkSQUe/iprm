"""Perf: прибрати невикористаний індекс (profile, path)

Revision ID: perf_drop_page_idx_20260725
Revises: perf_runs_20260725
Create Date: 2026-07-25 00:00:00.000000

Індекс створювався під тренд однієї сторінки в часі, але такої сторінки немає
-- жоден запит його не читає. Таблиця обмежена сотнею прогонів (~2 тис. рядків),
тож користі нуль, а вартість на кожній вставці є. Окрема міграція, а не правка
попередньої: та вже застосована.

Повернути індекс тривіально (downgrade), якщо зʼявиться сторінка тренду.
"""
from alembic import op


revision = 'perf_drop_page_idx_20260725'
down_revision = 'perf_runs_20260725'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index('ix_perf_page_metrics_profile_path', table_name='perf_page_metrics')


def downgrade():
    op.create_index(
        'ix_perf_page_metrics_profile_path', 'perf_page_metrics', ['profile', 'path'],
    )
