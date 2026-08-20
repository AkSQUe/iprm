"""Тренер підтверджує комплект: trainer_confirmed_at/trainer_comment на
резервуванні + created_by_id (хто подав заявку в ІПРМ).

Revision ID: trainer_confirm_20260820
Revises: online_login_20260820

Бриф завдання 6 фіксував `down_revision = 'material_kits_20260820'` (ревізія
завдання 3 цього ж плану) саме щоб не чіплятися за спільного предка
`material_cost_20260820` і не давати двох голів. Але поки виконувалось це
завдання, на `main` вже приїхала й закомітилась `online_login_20260820`
(інша, незалежна фіча, теж від `material_kits_20260820` -- перевірено
`git log` на файл і `flask db heads` до цієї зміни: після додавання файла
з `material_kits_20260820` голів стало ДВІ). Ланцюжок тут веде через неї,
а не напряму, щоб не створити саме ту розвилку, від якої застерігає бриф --
властивість «один головний ланцюг» важливіша за буквальний рядок ревізії,
яку бриф писав до появи online_login_20260820.
"""
import sqlalchemy as sa
from alembic import op

revision = 'trainer_confirm_20260820'
down_revision = 'online_login_20260820'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('material_reservations', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('trainer_confirmed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('trainer_comment', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('created_by_id', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            'fk_material_reservations_created_by_id', 'users',
            ['created_by_id'], ['id'], ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('material_reservations', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_material_reservations_created_by_id', type_='foreignkey')
        batch_op.drop_column('created_by_id')
        batch_op.drop_column('trainer_comment')
        batch_op.drop_column('trainer_confirmed_at')
