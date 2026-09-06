"""Тести сторінки /admin/settings."""
from tests.support.rbac import grant_role
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.user import User


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'a-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_settings_page_has_hero_video_toggle(client, admin):
    _login(client, admin)
    r = client.get('/admin/settings')
    assert r.status_code == 200
    assert b'show_home_hero_video' in r.data


def _form_payload(app, site, drop=()):
    """Поточні значення налаштувань у вигляді POST-даних форми.

    Форма має десятки обов'язкових полів, тож надсилати лише один чекбокс не
    можна -- валідація впаде і зміни не збережуться. Знятий чекбокс браузер
    просто не надсилає, це й моделює drop.
    """
    from app.admin.forms import SiteSettingsForm

    with app.test_request_context():
        form = SiteSettingsForm(obj=site)
        data = {}
        for field in form:
            if field.type in ('CSRFTokenField', 'SubmitField') or field.name in drop:
                continue
            value = field.data
            if isinstance(value, bool):
                if value:
                    data[field.name] = 'y'
            elif value is not None:
                data[field.name] = str(value)
    return data


def test_settings_post_unchecked_disables_hero_video(client, admin, app):
    from app.models.site_settings import SiteSettings

    _login(client, admin)
    site = SiteSettings.get()
    assert site.show_home_hero_video is True

    # Обидва набори даних знімаємо ДО першого POST: далі об'єкт налаштувань уже
    # змінений, і payload "як було" з нього не зібрати.
    payload_on = _form_payload(app, site)
    payload_off = _form_payload(app, site, drop=('show_home_hero_video',))

    r = client.post('/admin/settings', data=payload_off, follow_redirects=True)
    assert r.status_code == 200
    assert SiteSettings.get().show_home_hero_video is False

    # Повертаємо як було: роут комітить, тож стан переживає відкат фікстури.
    r = client.post('/admin/settings', data=payload_on, follow_redirects=True)
    assert r.status_code == 200
    assert SiteSettings.get().show_home_hero_video is True
