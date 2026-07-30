"""Course: final CTA sentence

Revision ID: course_final_cta_20260730
Revises: soft_delete_undo_20260725
Create Date: 2026-07-30 00:00:00.000000

Додає courses.final_cta_text -- одне речення для фінального CTA-блоку внизу
сторінки курсу. NULL/порожньо -> шаблон показує дефолтний текст.
"""
from alembic import op
import sqlalchemy as sa


revision = 'course_final_cta_20260730'
down_revision = 'soft_delete_undo_20260725'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('final_cta_text', sa.String(length=300),
                                      nullable=True))


def downgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_column('final_cta_text')
