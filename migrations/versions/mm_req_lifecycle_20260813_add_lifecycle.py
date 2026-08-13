"""Життєвий цикл запиту матеріалів: походження, номер документа, чотири кількості

Revision ID: mm_req_lifecycle_20260813
Revises: phone_e164_20260811
Create Date: 2026-08-13 12:00:00.000000

MM Medic отримує крок погодження (тренер подає -> менеджер погоджує ->
комірник відвантажує -> повернення), тож запит тепер живе ЩЕ ДО того, як
з'явиться утримання складу. Дзеркалу потрібні:

  origin -- хто почав запит. Обидва входи (адмін ІПРМ і тренер у MM Medic)
    дають один документ під тим самим external_ref; поле впливає лише на
    формулювання в інтерфейсі.
  document_number -- номер, який MM Medic присвоює документу.
  remote_updated_at -- відмітка часу з останнього застосованого штовха.
    MM Medic шле їх окремим потоком без гарантії порядку, тож без цього
    поля старіший знімок міг би перекрити новіший.

Кількості на рядку: було дві (reserved, actual), стає п'ять. Дві наявні
зберігають зміст, щоб наявні екрани й підсумки не переписувати:
  requested -- скільки просив тренер
  reserved  -- скільки погоджено й утримується
  issued    -- скільки видано
  returned  -- скільки повернуто
  actual    -- спожито = issued - returned

Бекфіл: історичним рядкам requested = reserved. Це не здогад -- у старому
потоці адміністратор ІПРМ вводив кількість, і вона резервувалась один в один.
issued/returned для історії лишаються NULL: розкладки на видане й повернуте
тоді не існувало, і вигадувати її заднім числом не можна.

Статус зберігається як звичайний рядок без CHECK-обмеження, тож нові значення
(submitted, issued, rejected) міграції не потребують.
"""
from alembic import op
import sqlalchemy as sa


revision = 'mm_req_lifecycle_20260813'
down_revision = 'phone_e164_20260811'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('material_reservations') as batch:
        batch.add_column(sa.Column(
            'origin', sa.String(length=20), nullable=False,
            server_default='iprm',
        ))
        batch.add_column(sa.Column(
            'document_number', sa.String(length=50), nullable=True,
        ))
        batch.add_column(sa.Column(
            'remote_updated_at', sa.DateTime(timezone=True), nullable=True,
        ))

    with op.batch_alter_table('material_reservation_items') as batch:
        batch.add_column(sa.Column('quantity_requested', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('quantity_issued', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('quantity_returned', sa.Integer(), nullable=True))

    op.execute(
        'UPDATE material_reservation_items '
        'SET quantity_requested = quantity_reserved '
        'WHERE quantity_requested IS NULL'
    )


def downgrade():
    with op.batch_alter_table('material_reservation_items') as batch:
        batch.drop_column('quantity_returned')
        batch.drop_column('quantity_issued')
        batch.drop_column('quantity_requested')

    with op.batch_alter_table('material_reservations') as batch:
        batch.drop_column('remote_updated_at')
        batch.drop_column('document_number')
        batch.drop_column('origin')
