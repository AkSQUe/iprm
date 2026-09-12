"""Partner-linked accounts: provider='partner' in auth_identities CHECK

Revision ID: partner_identity_20260912
Revises: instance_difficulty_20260910
Create Date: 2026-09-12 00:00:00.000000

Партнерський лінк (prefill-токен з mm-medic) доти заводив акаунт із
випадковим паролем token_urlsafe(32): людина не могла ні увійти, ні
встановити пароль у кабінеті. Тепер такий акаунт -- без пароля, з
identity-маркером provider='partner', за яким форма реєстрації називає
джерело. CHECK дозволяв лише password/google/apple, тож розширюємо його.

Даних міграція не чіпає: наявні акаунти лишаються як є (для точкового
переведення є CLI `flask partner-relink <email>`).
"""
from alembic import op


revision = 'partner_identity_20260912'
down_revision = 'instance_difficulty_20260910'
branch_labels = None
depends_on = None

_PROVIDERS_OLD = "provider IN ('password', 'google', 'apple')"
_PROVIDERS_NEW = "provider IN ('password', 'google', 'apple', 'partner')"


def upgrade():
    op.drop_constraint('ck_auth_identities_provider', 'auth_identities',
                       type_='check')
    op.create_check_constraint('ck_auth_identities_provider', 'auth_identities',
                               _PROVIDERS_NEW)


def downgrade():
    # Партнерські рядки порушили б вужчий CHECK -- знімаємо їх разом із
    # ним. Пароля вони не несуть, тож входу нікому не ламають: акаунти
    # лишаються, просто знову без маркера джерела.
    op.execute("DELETE FROM auth_identities WHERE provider = 'partner'")
    op.drop_constraint('ck_auth_identities_provider', 'auth_identities',
                       type_='check')
    op.create_check_constraint('ck_auth_identities_provider', 'auth_identities',
                               _PROVIDERS_OLD)
