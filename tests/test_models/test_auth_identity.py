"""AuthIdentity: перелік провайдерів і CHECK мусять збігатися.

Той самий клас багів, що й з тригерами листів: константу в моделі
розширили, CHECK у БД -- ні, і INSERT падає вже на проді.
"""
import re

from sqlalchemy import CheckConstraint

from app.models.auth_identity import AuthIdentity


def test_check_constraint_matches_providers():
    sqltext = None
    for c in AuthIdentity.__table__.constraints:
        if isinstance(c, CheckConstraint) and c.name == 'ck_auth_identities_provider':
            sqltext = str(c.sqltext)
            break
    assert sqltext is not None, 'CHECK ck_auth_identities_provider не знайдено в моделі'
    in_constraint = set(re.findall(r"'([a-z_]+)'", sqltext))
    assert in_constraint == set(AuthIdentity.PROVIDERS), (
        'CHECK і AuthIdentity.PROVIDERS розійшлися: '
        f'{in_constraint ^ set(AuthIdentity.PROVIDERS)}'
    )


def test_partner_provider_is_registered():
    assert AuthIdentity.PROVIDER_PARTNER in AuthIdentity.PROVIDERS
