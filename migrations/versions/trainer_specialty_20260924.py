"""Колонка specialty у trainer_profiles.

Спеціальність за освітою в анкеті тренера -- поле поруч з освітою. Для
резюме до реєстру БПР: окрема колонка таблиці й підписаний рядок у клітинці
освіти офіційної форми. Необовʼязкове: в REQUIRED_FOR_COMPLETE не входить,
тож наявні анкети не стають неповними.

Revision ID: trainer_specialty_20260924
Revises: proposal_title_len_20260924
"""
import sqlalchemy as sa
from alembic import op

revision = 'trainer_specialty_20260924'
down_revision = 'proposal_title_len_20260924'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trainer_profiles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('specialty', sa.String(length=255)))


def downgrade():
    with op.batch_alter_table('trainer_profiles', schema=None) as batch_op:
        batch_op.drop_column('specialty')
