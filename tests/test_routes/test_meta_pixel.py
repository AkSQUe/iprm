"""Тести інтеграції Meta Pixel: модель, адмін-сторінка, рендер, CSP."""
from tests.support.rbac import grant_role
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.user import User


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'mp-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='M', last_name='P', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.flush()
    return u


@pytest.fixture
def site():
    """SiteSettings -- singleton (id=1), спільний на всю сесію тестів.

    Роути інтеграцій комітять усередині запиту, і цей коміт переживає відкат
    db_session-фікстури, тож без явного скидання тест бачив би Pixel,
    увімкнений сусіднім тестом. Скидаємо до дефолту на вході.
    """
    s = SiteSettings.get()
    s.meta_pixel_id = ''
    # None, а не False: прапорець тристанний, і явний False тепер ПЕРЕКРИВАЄ
    # env. Скидати треба саме в "не задано", інакше жоден тест env-фолбеку
    # не мав би шансу спрацювати.
    s.meta_pixel_enabled = None
    db.session.commit()
    return s


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _enable(site, pixel_id='123456789012345'):
    site.meta_pixel_id = pixel_id
    site.meta_pixel_enabled = True
    db.session.flush()


# --- валідатор формату -------------------------------------------------

@pytest.mark.parametrize('value', ['123456789012345', '1234567890123456', ''])
def test_valid_pixel_ids(value):
    assert SiteSettings.is_valid_meta_pixel_id(value) is True


@pytest.mark.parametrize('value', [
    '12345',                     # закоротко
    '12345678901234567',         # задовго
    'G-ABCDEFGH',                # це GA, не Pixel
    '1234 5678 9012 345',        # з пробілами
    "fbq('init', '123456789012345')",  # вставили весь snippet
])
def test_invalid_pixel_ids(value):
    assert SiteSettings.is_valid_meta_pixel_id(value) is False


# --- effective_meta_pixel_id ------------------------------------------

def test_effective_id_empty_by_default(app, site):
    assert site.effective_meta_pixel_id == ''


def test_effective_id_from_db(app, site):
    _enable(site)
    assert site.effective_meta_pixel_id == '123456789012345'


def test_db_id_with_flag_off_disables_tracking(app, site):
    """Знятий прапорець вимикає Pixel, навіть якщо ID збережено."""
    _enable(site)
    site.meta_pixel_enabled = False
    db.session.flush()
    assert site.effective_meta_pixel_id == ''


def test_env_fallback_requires_both_vars(app, site):
    """Сам лише META_PIXEL_ID трекінг не вмикає.

    Прапорець у БД тут NULL ("в адмінці не задано"), тож рішення справді
    належить env. Якби він був явним False, env не мав би права голосу --
    саме це й перевіряє test_db_flag_off_wins_over_env нижче.
    """
    app.config['META_PIXEL_ID'] = '999999999999999'
    app.config['META_PIXEL_ENABLED'] = False
    try:
        assert site.effective_meta_pixel_id == ''
        app.config['META_PIXEL_ENABLED'] = True
        assert site.effective_meta_pixel_id == '999999999999999'
    finally:
        app.config['META_PIXEL_ID'] = ''
        app.config['META_PIXEL_ENABLED'] = False


def test_kill_switch_works_with_env_id(app, site):
    """Аварійний рубильник діє й тоді, коли ID приходить З ENV.

    Регресія на реальний дефект: доти прапорець дивився на наявність ID В БД,
    тож при ID зі змінних оточення зняття галки не робило нічого. Meta була
    останнім з трьох трекерів, де це лишалось зламаним (PostHog і GA
    полагоджено раніше того самого дня).
    """
    site.meta_pixel_id = ''
    site.meta_pixel_enabled = False
    db.session.flush()
    app.config['META_PIXEL_ID'] = '999999999999999'
    app.config['META_PIXEL_ENABLED'] = True
    try:
        assert site.effective_meta_pixel_id == '', (
            'вимкнення в адмінці не спрацювало при ID з env'
        )
    finally:
        app.config['META_PIXEL_ID'] = ''
        app.config['META_PIXEL_ENABLED'] = False


def test_null_flag_inherits_env(app, site):
    """NULL означає "в адмінці не задано" -- вирішує env."""
    assert site.meta_pixel_enabled is None
    app.config['META_PIXEL_ID'] = '999999999999999'
    app.config['META_PIXEL_ENABLED'] = True
    try:
        assert site.effective_meta_pixel_id == '999999999999999'
    finally:
        app.config['META_PIXEL_ID'] = ''
        app.config['META_PIXEL_ENABLED'] = False


def test_db_flag_off_wins_over_env(app, site):
    """Вимкнення в адмінці не має мовчки скасовуватись env-фолбеком."""
    site.meta_pixel_id = '123456789012345'
    site.meta_pixel_enabled = False
    db.session.flush()
    app.config['META_PIXEL_ID'] = '999999999999999'
    app.config['META_PIXEL_ENABLED'] = True
    try:
        assert site.effective_meta_pixel_id == ''
    finally:
        app.config['META_PIXEL_ID'] = ''
        app.config['META_PIXEL_ENABLED'] = False


# --- рендер на публічних сторінках ------------------------------------

def test_pixel_not_rendered_when_disabled(client, site):
    r = client.get('/')
    assert r.status_code == 200
    assert b'meta-pixel.js' not in r.data
    assert b'connect.facebook.net' not in r.headers.get(
        'Content-Security-Policy', '').encode()


def test_pixel_rendered_when_enabled(client, site):
    _enable(site)
    r = client.get('/')
    assert r.status_code == 200
    assert b'meta-pixel.js' in r.data
    assert b'data-pixel-id="123456789012345"' in r.data
    # події конверсій підключаються лише разом з активним Pixel
    assert b'meta-events.js' in r.data


def test_pixel_never_loads_in_admin(client, admin, site):
    """URL адмінки містять ідентифікатори клієнтів, а перегляди адмінів
    псують статистику -- Pixel там не працює навіть з увімкненим трекінгом."""
    _enable(site)
    _login(client, admin)
    r = client.get('/admin/integrations')
    assert r.status_code == 200
    assert b'meta-pixel.js' not in r.data
    assert b'meta-events.js' not in r.data


def test_csp_has_no_meta_domains_in_admin(client, admin, site):
    """CSP мусить збігатися з фактом: скрипта немає -- доменів теж."""
    _enable(site)
    _login(client, admin)
    csp = client.get('/admin/integrations').headers.get('Content-Security-Policy', '')
    assert 'connect.facebook.net' not in csp


def test_test_page_forces_pixel(client, admin, site):
    """Єдиний виняток із виключення адмінки: без завантаженого скрипта
    перевіряти нічого."""
    _enable(site)
    _login(client, admin)
    r = client.get('/admin/meta-pixel/test')
    assert r.status_code == 200
    assert b'meta-pixel.js' in r.data
    csp = r.headers.get('Content-Security-Policy', '')
    assert 'connect.facebook.net' in csp


def test_test_page_redirects_when_pixel_off(client, admin, site):
    _login(client, admin)
    r = client.get('/admin/meta-pixel/test')
    assert r.status_code == 302


def test_course_page_sends_view_content(client, site):
    """ViewContent -- база ремаркетингу; має бути на сторінці курсу."""
    from app.models.course import Course
    _enable(site)
    slug = f'test-pixel-{uuid4().hex[:8]}'
    db.session.add(Course(
        title='Тестовий курс', slug=slug, is_active=True, base_price=4500,
    ))
    db.session.commit()
    try:
        r = client.get(f'/courses/{slug}')
        assert r.status_code == 200
        body = r.data.decode('utf-8')
        assert 'data-meta-event-load="ViewContent"' in body
        assert f'data-meta-param-content-ids="{slug}"' in body
        assert 'data-meta-param-value="4500"' in body
    finally:
        Course.query.filter_by(slug=slug).delete()
        db.session.commit()


def test_csp_allows_meta_domains_only_when_enabled(client, site):
    _enable(site)
    csp = client.get('/').headers.get('Content-Security-Policy', '')
    assert 'https://connect.facebook.net' in csp
    assert 'https://www.facebook.com' in csp


def test_no_inline_pixel_snippet(client, site):
    """No Inline Policy: snippet живе у зовнішньому файлі, не в HTML."""
    _enable(site)
    body = client.get('/').data
    assert b"fbq('init'" not in body
    assert b'fbq("init"' not in body


# --- адмін-сторінка ---------------------------------------------------

def test_admin_page_renders(client, admin, site):
    _login(client, admin)
    r = client.get('/admin/meta-pixel')
    assert r.status_code == 200
    assert b'meta_pixel_id' in r.data


def test_admin_page_requires_admin(client):
    r = client.get('/admin/meta-pixel')
    assert r.status_code in (302, 401, 403)


def test_save_valid_id(client, admin, site):
    _login(client, admin)
    r = client.post('/admin/meta-pixel/save', data={
        'meta_pixel_id': '123456789012345',
        'meta_pixel_enabled': 'on',
    }, follow_redirects=True)
    assert r.status_code == 200
    s = SiteSettings.get()
    assert s.meta_pixel_id == '123456789012345'
    assert s.meta_pixel_enabled is True


def test_save_rejects_bad_format(client, admin, site):
    _login(client, admin)
    client.post('/admin/meta-pixel/save', data={
        'meta_pixel_id': 'not-a-pixel',
        'meta_pixel_enabled': 'on',
    }, follow_redirects=True)
    assert SiteSettings.get().meta_pixel_id == ''


def test_save_rejects_enable_without_id(client, admin, site):
    """Увімкнено + порожній ID дало б бейдж 'Активно' без трекінгу."""
    _login(client, admin)
    client.post('/admin/meta-pixel/save', data={
        'meta_pixel_enabled': 'on',
    }, follow_redirects=True)
    # `is not True`, а не `is False`: форму відхилено, тож у БД лишається
    # те, що там було -- а тристанний прапорець цілком може бути None.
    assert SiteSettings.get().meta_pixel_enabled is not True


def test_save_keeps_id_when_disabling(client, admin, site):
    """Вимкнення не стирає ID -- інакше вмикати довелось би заново."""
    _enable(site)
    _login(client, admin)
    client.post('/admin/meta-pixel/save', data={
        'meta_pixel_id': '123456789012345',
    }, follow_redirects=True)
    s = SiteSettings.get()
    assert s.meta_pixel_id == '123456789012345'
    assert s.meta_pixel_enabled is False


def test_integrations_hub_links_to_pixel(client, admin, site):
    _login(client, admin)
    r = client.get('/admin/integrations')
    assert r.status_code == 200
    assert b'/admin/meta-pixel' in r.data


# --- export/import конфігурації ---------------------------------------

def test_cookie_policy_mentions_meta_pixel(client):
    """Політика Cookie мусить називати трекер, який ми ставимо -- інакше
    сторінка суперечить коду (і GDPR)."""
    body = client.get('/cookies').data.decode('utf-8')
    assert 'Meta Pixel' in body
    assert '_fbp' in body


def test_privacy_policy_lists_meta_as_recipient(client):
    """Meta -- отримувач даних, і розділ про передачу третім особам мусить
    його перелічувати."""
    body = client.get('/privacy').data.decode('utf-8')
    assert 'Meta Platforms' in body


def test_config_export_includes_pixel(app, site):
    from app.services.integration_config_io import export_env
    _enable(site)
    text = export_env(site, include_secrets=False)
    assert 'META_PIXEL_ID=123456789012345' in text
    assert 'META_PIXEL_ENABLED=true' in text
