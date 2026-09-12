"""Переведення наявного акаунта на партнерські рейки.

Акаунти, заведені prefill-лінком ДО 12.09.2026, несуть випадковий пароль
``secrets.token_urlsafe(32)``: увійти з ним не може ніхто, а кабінет на
спробу встановити пароль відповідає "Пароль уже встановлено". Нового коду
їм замало -- він діє лише на тих, кого заводять тепер.

Команда точкова, за адресою: партнерські акаунти нічим не помічені в БД,
тож гуртом їх не відібрати. Розсилки вона не робить -- лише прибирає
фальшивий пароль і ставить маркер джерела.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.user import User
from tests.support.users import wipe_users

EMAIL_PREFIXES = ('relink-', 'empty-pw-')


@pytest.fixture(autouse=True)
def clean(app):
    """Прибрати за собою: тестова БД спільна на всю сесію (див.
    tests/support/users.py -- залишені акаунти валять чужі тести)."""
    wipe_users(*EMAIL_PREFIXES)
    yield
    wipe_users(*EMAIL_PREFIXES)


def _email():
    return f'relink-{uuid4().hex[:8]}@test.com'


@pytest.fixture
def legacy_partner_user(app):
    """Акаунт у стані, який робила стара версія get_or_create_partner_user."""
    user = User.create_with_password(
        email=_email(), password='irretrievable-random-secret',
        first_name='Анатолій', last_name='Луньов',
        email_confirmed=True, is_active=True,
    )
    db.session.commit()
    return user


def _run(app, *args):
    return app.test_cli_runner().invoke(args=['partner-relink', *args])


class TestPartnerRelink:

    def test_drops_unusable_password(self, app, legacy_partner_user):
        _run(app, legacy_partner_user.email)
        assert legacy_partner_user.has_password is False

    def test_adds_partner_marker(self, app, legacy_partner_user):
        _run(app, legacy_partner_user.email)
        identity = AuthIdentity.query.filter_by(
            user_id=legacy_partner_user.id,
            provider=AuthIdentity.PROVIDER_PARTNER,
        ).first()
        assert identity is not None
        assert identity.raw_claims['issuer'] == 'mm-medic'

    def test_is_idempotent(self, app, legacy_partner_user):
        _run(app, legacy_partner_user.email)
        result = _run(app, legacy_partner_user.email)
        assert result.exit_code == 0
        assert AuthIdentity.query.filter_by(
            user_id=legacy_partner_user.id,
            provider=AuthIdentity.PROVIDER_PARTNER,
        ).count() == 1

    def test_unknown_email_fails_loudly(self, app):
        result = _run(app, 'nobody-here@test.com')
        assert result.exit_code != 0

    def test_dry_run_changes_nothing(self, app, legacy_partner_user):
        _run(app, legacy_partner_user.email, '--dry-run')
        assert legacy_partner_user.has_password is True
        assert AuthIdentity.query.filter_by(
            user_id=legacy_partner_user.id,
            provider=AuthIdentity.PROVIDER_PARTNER,
        ).count() == 0

    def test_empty_password_identity_is_left_alone(self, app):
        """Рядок без хеша входу не дає -- прибирати нема чого.

        Такий стан має OAuth-юзер, що пароля ще не ставив. Трактувати його
        як "непридатний пароль" означало б рапортувати про роботу, якої
        не було.
        """
        user = User(email=_email(), email_confirmed=True)
        db.session.add(user)
        db.session.flush()
        db.session.add(AuthIdentity(
            user_id=user.id, provider=AuthIdentity.PROVIDER_PASSWORD,
            provider_sub=str(user.id), email=user.email,
        ))
        db.session.commit()

        result = _run(app, user.email)

        assert result.exit_code == 0
        assert 'непридатний пароль' not in result.output
        assert AuthIdentity.query.filter_by(
            user_id=user.id, provider=AuthIdentity.PROVIDER_PASSWORD).count() == 1

    def test_unknown_issuer_is_rejected(self, app, legacy_partner_user):
        """issuer їде в raw_claims, а звідти -- у текст на формі реєстрації."""
        result = _run(app, legacy_partner_user.email, '--issuer', 'evil-corp')

        assert result.exit_code != 0
        assert legacy_partner_user.has_password is True
