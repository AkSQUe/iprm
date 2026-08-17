"""Посилання на кабінет у листі про сертифікат.

Кнопка «Відкрити особистий кабінет» склеювалась у шаблоні як
`website_url ~ "/account"`. Такого маршруту немає -- кабінет живе на
`/auth/account`, тож кнопка в кожному виданому сертифікаті вела у 404. Решта
листів будують шлях у сервісі (`f'{base}/auth/account'`), і цей був винятком.
"""

import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.services.email_service import EmailService


@pytest.fixture
def settings(app):
    s = SiteSettings.get()
    s.website_url = 'https://iprm.space'
    db.session.flush()
    return s


def test_account_url_points_to_existing_route(app, settings):
    assert EmailService._account_url() == 'https://iprm.space/auth/account'


def test_account_url_is_a_real_route(app, settings):
    """Найголовніше: шлях мусить існувати в url_map, а не просто бути гарним."""
    from urllib.parse import urlparse

    path = urlparse(EmailService._account_url()).path
    rules = {str(r) for r in app.url_map.iter_rules()}
    assert path in rules, f'{path} немає серед маршрутів'


def test_trailing_slash_in_settings_does_not_double(app, settings):
    settings.website_url = 'https://iprm.space/'
    db.session.flush()
    assert EmailService._account_url() == 'https://iprm.space/auth/account'


def test_empty_website_url_falls_back_to_relative(app, settings):
    settings.website_url = ''
    db.session.flush()
    assert EmailService._account_url() == '/auth/account'


def test_domain_follows_settings(app, settings):
    settings.website_url = 'https://example.org'
    db.session.flush()
    assert EmailService._account_url().startswith('https://example.org/')


def test_template_uses_context_not_hardcoded_path(app, settings):
    """Шаблон не має сам склеювати URL -- інакше правка домену його мине.

    Jinja-коментарі вирізаємо: у самому шаблоні пояснено, що там стояло раніше,
    і без цього тест ловив би власний коментар.
    """
    import re
    from pathlib import Path

    source = Path(app.root_path, 'templates', 'emails',
                  'certificate_issued.html').read_text(encoding='utf-8')
    code = re.sub(r'\{#.*?#\}', '', source, flags=re.DOTALL)

    assert 'account_url' in code
    assert 'website_url' not in code


def test_no_old_domain_left_in_app(app):
    """Старий домен не має бути зашитий ніде: він устарів при переїзді."""
    import re
    from pathlib import Path

    root = Path(app.root_path)
    offenders = []
    for path in list(root.rglob('*.py')) + list(root.rglob('*.html')):
        text = path.read_text(encoding='utf-8', errors='ignore')
        if re.search(r'plasma-regen\.com', text):
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f'зашитий старий домен: {offenders}'
