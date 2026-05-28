"""Phase 7 cleanup: drop legacy User medical/auth columns

Завершення auth unification refactor. Після Phase 1 backfill і Phase 2-6
рефакторингів усі ці поля живуть у власних таблицях:
  - password_hash         -> auth_identities.password_hash
  - user_type             -> medical_profiles.participant_type
  - middle_name           -> medical_profiles.middle_name
  - birth_date            -> medical_profiles.birth_date
  - education             -> medical_profiles.education
  - workplace             -> medical_profiles.workplace
  - position              -> medical_profiles.position
  - phone                 -> medical_profiles.phone
  - specializations       -> medical_profiles.specializations

ck_users_user_type check constraint -- залежить від колонки user_type,
тому дропаємо його першим.

DESTRUCTIVE: незворотний drop columns у проді. Перед застосуванням
переконайтесь, що:
  1) backfill з Phase 1 (e3f4a5b6c7d8) успішний для всіх users;
  2) усі читачі переведені на canonical (audit показав 0 external readers);
  3) prod app-код вже не пише в ці колонки (Phase 7 уже задеплоєний).

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-05-28 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b6c7d8e9f0a1'
down_revision = 'a5b6c7d8e9f0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        # Check-constraint спершу (залежить від колонки).
        batch_op.drop_constraint('ck_users_user_type', type_='check')
        batch_op.drop_column('specializations')
        batch_op.drop_column('phone')
        batch_op.drop_column('position')
        batch_op.drop_column('workplace')
        batch_op.drop_column('education')
        batch_op.drop_column('birth_date')
        batch_op.drop_column('middle_name')
        batch_op.drop_column('user_type')
        batch_op.drop_column('password_hash')


def downgrade():
    """Відновлюємо колонки як nullable (відновити дані з MedicalProfile/
    AuthIdentity не пробуємо -- caller робить це окремим скриптом, якщо
    треба). password_hash робимо NOT NULL з server_default='' щоб таблиця
    лишилась валідною; це не відновить функціональність password-логіну
    через legacy шлях, але збереже схему."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('password_hash', sa.String(length=255),
                                       nullable=False, server_default=''))
        batch_op.add_column(sa.Column('user_type', sa.String(length=20),
                                       nullable=True))
        batch_op.add_column(sa.Column('middle_name', sa.String(length=100),
                                       nullable=True))
        batch_op.add_column(sa.Column('birth_date', sa.Date(),
                                       nullable=True))
        batch_op.add_column(sa.Column('education', sa.String(length=500),
                                       nullable=True))
        batch_op.add_column(sa.Column('workplace', sa.String(length=300),
                                       nullable=True))
        batch_op.add_column(sa.Column('position', sa.String(length=200),
                                       nullable=True))
        batch_op.add_column(sa.Column('phone', sa.String(length=20),
                                       nullable=True))
        batch_op.add_column(sa.Column('specializations', sa.JSON(),
                                       nullable=True))
        batch_op.create_check_constraint(
            'ck_users_user_type',
            "user_type IN ('doctor', 'specialist', 'intern', 'student') "
            "OR user_type IS NULL",
        )
