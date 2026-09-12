"""Партнерські акаунти видно в списку користувачів адмінки.

Вони поводяться інакше за решту -- пароля не мають, і людина заводила їх
не сама, -- але в списку доти нічим не відрізнялись. Разом із бейджем
перевіряємо, що ознака береться ПАКЕТОМ: `User.partner_issuer` б'є в
auth_identities на кожного користувача, і в списковому вигляді це той
самий слід, що вже описаний для `has_password` у meta-заявках.
"""
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models.user import User
from app.services.partner_auth import PrefillPayload, get_or_create_partner_user
from tests.support.rbac import grant_role
from tests.support.users import wipe_users

EMAIL_PREFIXES = ('pb-admin-', 'pb-partner-')


@pytest.fixture(autouse=True)
def clean(app):
    wipe_users(*EMAIL_PREFIXES)
    yield
    wipe_users(*EMAIL_PREFIXES)


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'pb-admin-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='А', last_name='Адмін', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def _partner(n=1):
    made = []
    for _ in range(n):
        made.append(get_or_create_partner_user(PrefillPayload(
            email=f'pb-partner-{uuid4().hex[:8]}@test.com',
            first_name='А', last_name='Б', phone=None, issuer='mm-medic',
        )))
    return made


def test_partner_account_is_labelled(client, admin):
    _partner()
    _login(client, admin)
    html = client.get('/admin/users').get_data(as_text=True)
    assert 'MM Medic' in html


def test_counter_shows_how_many(client, admin):
    _partner(2)
    _login(client, admin)
    html = client.get('/admin/users').get_data(as_text=True)
    assert 'Партнерських:' in html


def test_ordinary_account_gets_no_label(client, admin):
    """Бейдж не має чіплятись до всіх підряд."""
    _login(client, admin)
    html = client.get('/admin/users').get_data(as_text=True)
    assert 'MM Medic' not in html


def test_lookup_does_not_grow_with_rows(client, admin):
    """Ознака береться одним запитом на сторінку, а не по рядку."""
    _login(client, admin)

    def _count():
        seen = []

        def _tap(_c, _cur, statement, _p, _ctx, _m):
            if statement.lstrip().upper().startswith('SELECT'):
                seen.append(statement)

        event.listen(db.engine, 'before_cursor_execute', _tap)
        try:
            client.get('/admin/users')
        finally:
            event.remove(db.engine, 'before_cursor_execute', _tap)
        return len(seen)

    _partner(1)
    few = _count()
    _partner(10)
    many = _count()

    assert many - few <= 2, (
        f'запитів побільшало з {few} до {many}: ознака береться по рядку')
