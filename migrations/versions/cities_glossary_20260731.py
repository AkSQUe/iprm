"""Довідник назв локацій (cities) для перекладу розкладу

Revision ID: cities_glossary_20260731
Revises: i18n_srckey_20260731
Create Date: 2026-07-31 00:30:00.000000

CourseInstance.location лишається вільним текстом; переклад назви живе в
довіднику й підбирається звіркою нормалізованого рядка. Це дешевше за
перекладне поле на кожному проведенні: міста повторюються десятками
проведень, а нові проведення створюються постійно.

Таблиця порожня після створення -- поки в ній немає записів, локації
показуються як є (поточна поведінка).
"""
from alembic import op
import sqlalchemy as sa


revision = 'cities_glossary_20260731'
down_revision = 'i18n_srckey_20260731'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cities',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('name_normalized', sa.String(length=255), nullable=False),
        sa.Column('translations', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_cities_name'),
        sa.UniqueConstraint('name_normalized', name='uq_cities_name_normalized'),
    )
    with op.batch_alter_table('cities', schema=None) as batch_op:
        batch_op.create_index('ix_cities_name_normalized', ['name_normalized'])


def downgrade():
    with op.batch_alter_table('cities', schema=None) as batch_op:
        batch_op.drop_index('ix_cities_name_normalized')
    op.drop_table('cities')
