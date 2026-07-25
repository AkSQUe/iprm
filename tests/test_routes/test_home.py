"""Тести публічної Головної сторінки та маршрутизації каталогу."""


def test_home_renders_at_root(client):
    r = client.get('/')
    assert r.status_code == 200                      # більше не редірект
    assert b'page-home' in r.data
    assert 'Обрати курс'.encode() in r.data


def test_home_is_not_redirect(client):
    # Раніше / робив 301 на каталог -- тепер це самостійна сторінка.
    r = client.get('/', follow_redirects=False)
    assert r.status_code == 200


def test_hero_video_rendered_by_default(client):
    r = client.get('/')
    assert b'data-hero-video' in r.data
    assert b'home-hero-video.js' in r.data


def test_hero_video_toggle_off_restores_plain_hero(client, db_session):
    from app.models.site_settings import SiteSettings

    site = SiteSettings.get()
    site.show_home_hero_video = False
    db_session.flush()

    r = client.get('/')
    assert r.status_code == 200
    # Ні розмітки, ні скрипта -- hero як до впровадження відео.
    assert b'data-hero-video' not in r.data
    assert b'home-hero-media' not in r.data
    assert b'home-hero-video.js' not in r.data


def test_catalog_lives_under_courses(client):
    # Каталог на /courses/ (trailing slash canonical).
    assert client.get('/courses/').status_code == 200
