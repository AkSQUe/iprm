"""Phase 1 of auth unification: auth_identities + medical_profiles tables + backfill

Створює дві нові таблиці і копіює дані з існуючих users:
  - auth_identities: для кожного user створюється рядок provider='password'
    з password_hash, email, email_verified=email_confirmed. provider_sub
    встановлюється у str(user.id) -- стабільний sub для нашої власної
    "password-провайдерної" системи.
  - medical_profiles: переноситься user_type, middle_name, birth_date,
    education, workplace, position, phone, specializations. completed_at
    встановлюється у created_at тільки якщо всі обов'язкові БПР-поля
    заповнені; інакше NULL. source='legacy' маркує backfill-вані рядки.

Backward-safe: старі колонки в users НЕ змінюються. Існуючий код
продовжує читати з users.password_hash, users.user_type, ... поки що
не зачіпається. У наступних фазах перехід на нові таблиці; legacy-
колонки дропнемо у Фазі 7.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-28 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade():
    # ----- auth_identities -----
    op.create_table(
        'auth_identities',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('provider_sub', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column(
            'email_verified', sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column('password_hash', sa.String(length=255), nullable=True),
        sa.Column('raw_claims', sa.JSON(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            ondelete='CASCADE',
            name='fk_auth_identities_user_id',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_auth_identities'),
        sa.UniqueConstraint(
            'provider', 'provider_sub',
            name='uq_auth_identities_provider_sub',
        ),
        sa.CheckConstraint(
            "provider IN ('password', 'google', 'apple')",
            name='ck_auth_identities_provider',
        ),
    )
    op.create_index(
        'ix_auth_identities_user_id', 'auth_identities', ['user_id'],
    )
    op.create_index(
        'ix_auth_identities_provider_email',
        'auth_identities', ['provider', 'email'],
    )

    # ----- medical_profiles -----
    op.create_table(
        'medical_profiles',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('participant_type', sa.String(length=20), nullable=True),
        sa.Column('middle_name', sa.String(length=100), nullable=True),
        sa.Column('birth_date', sa.Date(), nullable=True),
        sa.Column('education', sa.String(length=500), nullable=True),
        sa.Column('workplace', sa.String(length=300), nullable=True),
        sa.Column('position', sa.String(length=200), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('specializations', sa.JSON(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'source', sa.String(length=20),
            nullable=False, server_default='self',
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            ondelete='CASCADE',
            name='fk_medical_profiles_user_id',
        ),
        sa.PrimaryKeyConstraint('user_id', name='pk_medical_profiles'),
        sa.CheckConstraint(
            "participant_type IN ('doctor', 'specialist', 'intern', 'student') "
            "OR participant_type IS NULL",
            name='ck_medical_profiles_participant_type',
        ),
    )

    # ----- Backfill auth_identities -----
    # Для кожного існуючого user з password_hash створюємо provider='password'
    # identity. provider_sub = id (стабільний sub нашої власної системи).
    op.execute("""
        INSERT INTO auth_identities (
            user_id, provider, provider_sub, email, email_verified,
            password_hash, last_used_at, created_at, updated_at
        )
        SELECT
            id,
            'password',
            id::text,
            email,
            COALESCE(email_confirmed, false),
            password_hash,
            last_login_at,
            created_at,
            COALESCE(updated_at, created_at)
        FROM users
        WHERE password_hash IS NOT NULL AND password_hash <> ''
    """)

    # ----- Backfill medical_profiles -----
    # Кожен user отримує запис у medical_profiles (можливо порожній).
    # completed_at заповнюється тільки коли всі БПР-поля присутні.
    op.execute("""
        INSERT INTO medical_profiles (
            user_id, participant_type, middle_name, birth_date, education,
            workplace, position, phone, specializations,
            completed_at, source, created_at, updated_at
        )
        SELECT
            id,
            user_type,
            middle_name,
            birth_date,
            education,
            workplace,
            position,
            phone,
            specializations,
            CASE
                WHEN user_type IS NOT NULL
                 AND birth_date IS NOT NULL
                 AND education IS NOT NULL AND education <> ''
                 AND specializations IS NOT NULL
                 AND json_array_length(specializations) > 0
                THEN created_at
                ELSE NULL
            END,
            'legacy',
            created_at,
            COALESCE(updated_at, created_at)
        FROM users
    """)


def downgrade():
    op.drop_table('medical_profiles')
    op.drop_index(
        'ix_auth_identities_provider_email',
        table_name='auth_identities',
    )
    op.drop_index(
        'ix_auth_identities_user_id',
        table_name='auth_identities',
    )
    op.drop_table('auth_identities')
