"""Add medical-profile fields to users (МОЗ №725 п.13)

Revision ID: a8b9c0d1e2f3
Revises: f1a2b3c4d5e6
Create Date: 2026-05-22 18:30:00.000000

Phase 1 з оновлення реєстраційного flow під схожість з evopro.
Додаємо поля, що збираються один раз і живуть на User (не на
EventRegistration), щоб пре-заповнювати форму при повторних реєстраціях.

Усі поля nullable -- історичні користувачі не блокуються; нові валідації
вмикатимуться у формі (Фаза 2), не на рівні БД.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a8b9c0d1e2f3'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_type', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('middle_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('birth_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('education', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('workplace', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('position', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('phone', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('specializations', sa.JSON(), nullable=True))

        batch_op.create_check_constraint(
            'ck_users_user_type',
            "user_type IN ('doctor', 'specialist', 'intern', 'student') "
            "OR user_type IS NULL",
        )


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('ck_users_user_type', type_='check')
        batch_op.drop_column('specializations')
        batch_op.drop_column('phone')
        batch_op.drop_column('position')
        batch_op.drop_column('workplace')
        batch_op.drop_column('education')
        batch_op.drop_column('birth_date')
        batch_op.drop_column('middle_name')
        batch_op.drop_column('user_type')
