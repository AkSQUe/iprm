"""`_listing.page_arg()` і обрізання `text_arg()` -- хвости плану
`docs/superpowers/plans/2026-08-30-admin-listing-tails.md` (Task 1, Task 3).

Task 1: `?page=<величезне число>` кидав 500 (SQLite OverflowError / Postgres
"bigint out of range") на восьми пагінованих реєстрах адмінки, бо `page`
читався повз захист `int_arg` мав для id. Task 3: непорізаний `?q=...`
роздував чіпс і кожне посилання сторінки символами, яких запит однаково не
бачить (`search_clause` ріже до MAX_SEARCH_LENGTH до запиту).
"""
from tests.support.rbac import grant_role
import re
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from app.admin import _listing
from app.extensions import db
from app.models.b2b_request import B2BRequest

EMAIL_PREFIX = 'pa-'


def _uid():
    return uuid4().hex[:8]


@pytest.fixture(autouse=True)
def clean(app):
    """Прибрати власні B2BRequest (маркер у email) до і після теста."""
    def _wipe():
        B2BRequest.query.filter(
            B2BRequest.email.like(f'{EMAIL_PREFIX}%@test.local'),
        ).delete(synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def admin(app):
    from app.models.user import User

    user = User.create_with_password(
        f'{EMAIL_PREFIX}{_uid()}@test.com', 'password123',
        first_name='П', last_name='Аргумент', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.flush()
    return user


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _make_b2b(**overrides):
    kwargs = dict(
        first_name='Б2Б', last_name='Тест', phone='+380670000000',
        email=f'{EMAIL_PREFIX}{_uid()}@test.local', team_size='3-5',
        status='new',
    )
    kwargs.update(overrides)
    req = B2BRequest(**kwargs)
    db.session.add(req)
    return req


# --- Task 1: page_arg() ------------------------------------------------------

# Вісім пагінованих реєстрів, на яких зонд підтвердив 500 через
# `?page=99999999999999999999`.
ADMIN_LISTING_URLS = [
    '/admin/b2b-requests',
    '/admin/course-requests',
    '/admin/refund-requests',
    '/admin/reviews',
    '/admin/users',
    '/admin/blog/comments',
    '/admin/webhooks',
    '/admin/perf',
]


@pytest.mark.parametrize('url', ADMIN_LISTING_URLS)
def test_huge_page_returns_200_not_500(client, admin, url):
    """Раніше -- 500 (OverflowError/`bigint out of range`) на КОЖНІЙ з цих
    восьми сторінок; тепер `page_arg()` ловить значення до OFFSET."""
    _login(client, admin)
    resp = client.get(f'{url}?page=99999999999999999999')
    assert resp.status_code == 200


@pytest.mark.parametrize('raw', ['-1', '0', 'abc', '99999999999999999999'])
def test_page_arg_falls_back_to_default_for_bad_input(app, raw):
    """Контракт самої функції: будь-яке не-число, 0, від'ємне чи значення
    понад стелю -- це default (1), а не сире значення з рядка запиту."""
    with app.test_request_context(f'/admin/users?page={raw}'):
        assert _listing.page_arg() == 1


def test_page_arg_accepts_the_ceiling_itself(app):
    """MAX_PAGE -- легітимна межа, не перше відкинуте значення: сторінка
    1_000_000 має дійти як є, а не впасти в default."""
    with app.test_request_context(f'/admin/users?page={_listing.MAX_PAGE}'):
        assert _listing.page_arg() == _listing.MAX_PAGE


def test_page_arg_rejects_just_above_the_ceiling(app):
    with app.test_request_context(f'/admin/users?page={_listing.MAX_PAGE + 1}'):
        assert _listing.page_arg() == 1


def test_normal_page_still_works(app, client, admin):
    """`?page=2` і далі гортає реєстр так само, як до правки."""
    _login(client, admin)
    # 26 заявок по 25 на сторінку -- рівно дві сторінки; остання (найстаріша
    # за created_at, бо запит сортує спаданням) лишається сама на другій.
    from datetime import datetime, timedelta, timezone

    base = datetime.now(timezone.utc)
    for i in range(26):
        req = _make_b2b(created_at=base - timedelta(minutes=26 - i))
        if i == 0:
            req.last_name = 'ЄдинаНаДругій'
    db.session.commit()

    resp1 = client.get('/admin/b2b-requests?page=1&per_page=25')
    resp2 = client.get('/admin/b2b-requests?page=2&per_page=25')
    assert resp1.status_code == 200 and resp2.status_code == 200
    assert 'ЄдинаНаДругій' not in resp1.get_data(as_text=True)
    assert 'ЄдинаНаДругій' in resp2.get_data(as_text=True)


# --- Task 3: text_arg() truncation ------------------------------------------

def test_search_string_capped_in_chip_and_links(app, client, admin):
    """`?q=<200 символів>` -- у чіпсі й у кожному посиланні сторінки має
    лишитись рівно 100: усе, що понад, `search_clause` однаково відкидав би
    до запиту, а тут воно лише роздувало URL."""
    _login(client, admin)
    term = 'Z' * 100 + 'X' * 100  # перші 100 -- те, що має лишитись
    resp = client.get('/admin/b2b-requests?' + urlencode({'q': term}))
    html = resp.get_data(as_text=True)

    # Лише href-и самої сторінки (чіпс, скидання, експорт, пагінатор) --
    # НЕ <meta property="og:url">, той навмисно дзеркалить сирий request.url
    # і до жодного з чотирьох посилань з проби Task 3 не належить.
    q_values = re.findall(r'href="[^"]*?q=([^&"]+)', html)
    assert q_values, 'на сторінці має бути хоч одне посилання з q= (чіпс)'
    for value in q_values:
        assert value == 'Z' * 100

    chip_match = re.search(r'Пошук:</span>\s*([^<]*)', html)
    assert chip_match is not None
    assert chip_match.group(1).strip() == 'Z' * 100


def test_truncated_search_still_finds_match(app, client, admin):
    """Перших 100 символів досить, щоб знайти запис, чиє поле саме на них
    і збігається -- обрізання не ламає сам пошук."""
    _login(client, admin)
    matching_term = 'Z' * 100
    _make_b2b(first_name=matching_term, last_name='ZMatch')
    db.session.commit()

    term = matching_term + 'X' * 100  # 200 символів, за межею MAX_SEARCH_LENGTH
    resp = client.get('/admin/b2b-requests?' + urlencode({'q': term}))
    html = resp.get_data(as_text=True)
    assert 'ZMatch' in html
