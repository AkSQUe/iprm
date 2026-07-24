"""Мовний роутинг: uk без префікса, /ru|/en з префіксом, /uk -> 301,
перемикач мов, hreflang, get_locale, sitemap-локалізація."""
import xml.etree.ElementTree as ET

from app.extensions import db
from app.i18n import get_locale
from app.models.course import Course


def _course(slug='c-route'):
    c = Course(title='Курс', slug=slug, is_active=True)
    db.session.add(c)
    db.session.flush()
    db.session.commit()
    return c


def test_uk_unprefixed_dispatch(client):
    assert client.get('/').status_code == 200
    assert client.get('/courses/').status_code == 200


def test_ru_en_prefixed_dispatch(client):
    assert client.get('/ru/').status_code == 200
    assert client.get('/en/').status_code == 200
    assert client.get('/ru/courses/').status_code == 200


def test_invalid_language_prefix_404(client):
    assert client.get('/de/').status_code == 404
    assert client.get('/fr/courses/').status_code == 404


def test_uk_prefix_redirects_to_canonical(client):
    r = client.get('/uk/courses/', follow_redirects=False)
    assert r.status_code == 301
    assert r.headers['Location'] == '/courses/'


def test_uk_prefix_redirect_preserves_query(client):
    r = client.get('/uk/courses/?tag=prp', follow_redirects=False)
    assert r.status_code == 301
    assert r.headers['Location'] == '/courses/?tag=prp'


def test_html_lang_and_og_locale_per_prefix(get_localized):
    assert '<html lang="uk">' in get_localized('/').get_data(as_text=True)
    ru = get_localized('/ru/').get_data(as_text=True)
    assert '<html lang="ru">' in ru and 'ru_RU' in ru
    en = get_localized('/en/').get_data(as_text=True)
    assert '<html lang="en">' in en and 'en_US' in en


def test_language_switcher_links(get_localized):
    ru = get_localized('/ru/').get_data(as_text=True)
    assert 'aria-current="true">RU' in ru
    assert 'href="/en/"' in ru and 'href="/"' in ru


def test_session_language_sticky(client):
    client.get('/ru/')
    with client.session_transaction() as s:
        assert s.get('lang') == 'ru'


def test_uk_visitor_no_session_cookie(client):
    client.get('/')
    with client.session_transaction() as s:
        assert s.get('lang') is None


def test_set_lang_valid_and_redirect(client):
    r = client.get('/set-lang/en?next=/payments/x', follow_redirects=False)
    assert r.status_code == 302 and r.headers['Location'] == '/payments/x'
    with client.session_transaction() as s:
        assert s.get('lang') == 'en'


def test_set_lang_rejects_open_redirect(client):
    r = client.get('/set-lang/en?next=https://evil.com', follow_redirects=False)
    # Зовнішній редірект відкинуто -> безпечний локальний шлях (локалізована
    # головна для щойно обраної мови).
    loc = r.headers['Location']
    assert loc.startswith('/') and not loc.startswith('//')
    assert 'evil.com' not in loc


def test_set_lang_invalid_language_404(client):
    assert client.get('/set-lang/de?next=/').status_code == 404


def test_get_locale_priority(app):
    with app.test_request_context('/', headers={'Accept-Language': 'ru,en;q=0.8'}):
        assert get_locale() == 'ru'
    with app.test_request_context('/'):
        assert get_locale() == 'uk'


def test_get_locale_default_outside_request(app):
    with app.app_context():
        assert get_locale() == 'uk'


def test_hreflang_alternates_present(client):
    _course('c-href')
    html = client.get('/courses/c-href').get_data(as_text=True)
    for tag in ('hreflang="uk"', 'hreflang="ru"', 'hreflang="en"', 'hreflang="x-default"'):
        assert tag in html
    assert 'hreflang="ru" href="http://localhost/ru/courses/c-href"' in html


def test_legal_pages_not_localized(client):
    assert client.get('/offer').status_code == 200
    assert client.get('/ru/offer').status_code == 404
    assert '<link rel="alternate" hreflang=' not in client.get('/offer').get_data(as_text=True)


def test_sitemap_localized_with_alternates(client):
    _course('c-sitemap')
    xml = client.get('/sitemap.xml').get_data(as_text=True)
    ET.fromstring(xml.encode())
    assert '<loc>http://localhost/ru/courses/c-sitemap</loc>' in xml
    assert 'hreflang="x-default"' in xml
    # Юридичні -- один запис, без мовних дзеркал.
    assert xml.count('/offer</loc>') == 1
    assert '/ru/offer' not in xml
