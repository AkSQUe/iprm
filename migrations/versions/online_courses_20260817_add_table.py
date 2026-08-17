"""Каталог онлайн-курсів (дзеркало треків Sintegrum)

Revision ID: online_courses_20260817
Revises: sintegrum_cfg_20260817
Create Date: 2026-08-17 14:40:00.000000

Дзеркало, а не кеш: сторінки читають цю таблицю, тож недоступність
Sintegrum не робить розділ порожнім, а зовнішнім ключам є за що чіплятися
(замовлення посилаються на конкретний курс).

remote_* пише лише синхронізація; решта колонок -- редакторські й
переживають будь-яку кількість прогонів.

Курс, що зник із видачі Sintegrum, позначається is_vanished і НЕ
видаляється -- інакше оплачені замовлення лишились би без курсу.
"""
from alembic import op
import sqlalchemy as sa


revision = 'online_courses_20260817'
down_revision = 'sintegrum_cfg_20260817'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'online_courses',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'),
                  primary_key=True),

        # дані Sintegrum
        sa.Column('sintegrum_id', sa.Integer(), nullable=False),
        sa.Column('remote_name', sa.String(length=255), nullable=False),
        sa.Column('remote_description', sa.Text(), nullable=True),
        sa.Column('remote_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('remote_status', sa.Integer(), nullable=True),
        sa.Column('remote_parent_id', sa.Integer(), nullable=True),
        sa.Column('remote_payload', sa.JSON(), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_vanished', sa.Boolean(), nullable=False,
                  server_default=sa.false()),

        # наші дані
        sa.Column('slug', sa.String(length=200), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('short_description', sa.String(length=500), nullable=True),
        sa.Column('translations', sa.JSON(), nullable=True),
        sa.Column('price', sa.Numeric(10, 2), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False,
                  server_default='UAH'),
        sa.Column('duration_hours', sa.Integer(), nullable=True),
        sa.Column('cpd_points', sa.Integer(), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('is_featured', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('hero_media_id', sa.BigInteger(), nullable=True),
        sa.Column('card_media_id', sa.BigInteger(), nullable=True),
        sa.Column('access_url', sa.String(length=1000), nullable=True),
        sa.Column('access_ttl_hours', sa.Integer(), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(['hero_media_id'], ['media_files.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['card_media_id'], ['media_files.id'],
                                ondelete='SET NULL'),
        sa.UniqueConstraint('sintegrum_id', name='uq_online_courses_sintegrum_id'),
        sa.UniqueConstraint('slug', name='uq_online_courses_slug'),
        sa.CheckConstraint('price >= 0 OR price IS NULL',
                           name='ck_online_courses_price_non_negative'),
        sa.CheckConstraint('duration_hours > 0 OR duration_hours IS NULL',
                           name='ck_online_courses_duration_positive'),
        sa.CheckConstraint('access_ttl_hours > 0 OR access_ttl_hours IS NULL',
                           name='ck_online_courses_ttl_positive'),
    )
    op.create_index('ix_online_courses_sintegrum_id', 'online_courses',
                    ['sintegrum_id'])
    op.create_index('ix_online_courses_last_seen_at', 'online_courses',
                    ['last_seen_at'])
    # Публічний каталог -- єдиний гарячий запит по цій таблиці.
    op.create_index('ix_online_courses_published_sort', 'online_courses',
                    ['is_published', 'sort_order'])


def downgrade():
    op.drop_index('ix_online_courses_published_sort', table_name='online_courses')
    op.drop_index('ix_online_courses_last_seen_at', table_name='online_courses')
    op.drop_index('ix_online_courses_sintegrum_id', table_name='online_courses')
    op.drop_table('online_courses')
