"""Спільний шар: abs_url і макрос хлібних крихт."""
from flask_babel import refresh

from tests.test_seo.helpers import jsonld_blocks


class TestAbsUrl:
    def test_none_for_empty(self, app):
        abs_url = app.jinja_env.globals['abs_url']
        with app.test_request_context():
            assert abs_url(None) is None
            assert abs_url('') is None

    def test_absolutizes_relative_path(self, app):
        abs_url = app.jinja_env.globals['abs_url']
        with app.test_request_context('/', base_url='https://iprm.space'):
            assert abs_url('/media/a/b.webp') == 'https://iprm.space/media/a/b.webp'

    def test_leaves_absolute_untouched(self, app):
        abs_url = app.jinja_env.globals['abs_url']
        with app.test_request_context('/', base_url='https://iprm.space'):
            src = 'https://cdn.example/x.png'
            assert abs_url(src) == src


def _breadcrumb(html):
    crumbs = [
        b for b in jsonld_blocks(html) if b.get('@type') == 'BreadcrumbList'
    ]
    assert len(crumbs) == 1, f'Очікували рівно одну BreadcrumbList, є {len(crumbs)}'
    return crumbs[0]


class TestBreadcrumbsMacro:
    def test_list_page_breadcrumb_shape(self, client):
        resp = client.get('/trainers/')
        assert resp.status_code == 200
        items = _breadcrumb(resp.data.decode('utf-8'))['itemListElement']
        assert [i['position'] for i in items] == [1, 2]
        assert items[0]['item'].startswith('http')
        # Поточна сторінка не має "item" за специфікацією schema.org.
        assert 'item' not in items[1]

    def test_breadcrumb_names_follow_locale(self, client):
        """Раніше назви крихт були захардкоджені українською і не
        перекладались. Макрос бере їх з переданих рядків.

        flask_babel.refresh() між запитами: db_session (conftest) тримає
        один app context на весь тест, тож flask_babel кешує локаль на
        g._flask_babel і без refresh() інакше не побачить зміни мови між
        двома client.get() у межах одного тесту (у бойовому запиті цього
        не буває -- там на кожен HTTP-запит свій контекст)."""
        uk = _breadcrumb(client.get('/trainers/').data.decode('utf-8'))
        refresh()
        en = _breadcrumb(client.get('/en/trainers/').data.decode('utf-8'))
        assert uk['itemListElement'][1]['name'] != en['itemListElement'][1]['name']
