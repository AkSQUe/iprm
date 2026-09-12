"""Полінг bounce-ів вмикається з адмінки, а не лише з консолі.

`bounce_service` повністю написаний і підключений до планувальника, але
`EmailSettings.bounce_polling_enabled` не мав жодного елемента керування:
фіча існувала й була недосяжною. Наслідок видно було в розборі скарги на
відновлення пароля -- лист із статусом `sent` міг відбитися, і про це не
дізнавався ніхто.
"""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.email_settings import EmailSettings
from app.models.user import User
from tests.support.rbac import grant_role
from tests.support.users import wipe_users

EMAIL_PREFIX = 'bt-admin-'


@pytest.fixture(autouse=True)
def clean(app):
    wipe_users(EMAIL_PREFIX)
    settings = EmailSettings.get()
    was = settings.bounce_polling_enabled
    yield
    settings = EmailSettings.get()
    settings.bounce_polling_enabled = was
    db.session.commit()
    wipe_users(EMAIL_PREFIX)


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'{EMAIL_PREFIX}{uuid4().hex[:8]}@test.com', 'password123',
        first_name='А', last_name='Адмін', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def _save(client, **over):
    """POST форми налаштувань пошти з мінімально валідним набором полів."""
    data = {
        'smtp_server': 'mail.example.com', 'smtp_port': '465',
        'smtp_username': 'courses@example.com',
        'default_sender': 'courses@example.com', 'sender_name': 'ІПРМ',
        'reminder_days': '7,3,1',
    }
    data.update(over)
    return client.post('/admin/notifications/settings', data=data)


def test_checkbox_is_on_the_page(client, admin):
    _login(client, admin)
    html = client.get('/admin/notifications').get_data(as_text=True)
    assert 'bounce_polling_enabled' in html


def test_toggle_on_is_saved(client, admin):
    _login(client, admin)
    _save(client, bounce_polling_enabled='on')
    assert EmailSettings.get().bounce_polling_enabled is True


def test_toggle_off_is_saved(client, admin):
    _login(client, admin)
    _save(client, bounce_polling_enabled='on')
    _save(client)
    assert EmailSettings.get().bounce_polling_enabled is False
