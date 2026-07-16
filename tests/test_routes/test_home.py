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


def test_catalog_lives_under_courses(client):
    # Каталог на /courses/ (trailing slash canonical).
    assert client.get('/courses/').status_code == 200
