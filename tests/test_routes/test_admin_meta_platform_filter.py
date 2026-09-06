"""`platform` у реєстрі лідів Meta звіряється з довжиною колонки, а не зі
списком `_PLATFORM_OPTIONS` (fb/ig).

`MetaLead.platform` -- `String(10)`, який пишеться просто з payload Meta
(`app/services/meta_lead_ingest.py`, `_clip(raw_lead.get('platform'), 10)`).
Модель невідомі значення передбачає: `platform_label` має fallback на сире
значення (`app/models/meta_lead.py`). Раніше фільтр приймав лише 'fb'/'ig'
(`choice_arg`), тож лід з іншою платформою (наприклад, месенджер-форма
'msg') мовчки НЕ звужувався -- посилання на нього віддавало б увесь
реєстр, а не рядок, з якого клікнули.

Пошук (`q`) у `_leads_query` бʼється по ПІБ/пошті/телефону, не по
`leadgen_id` -- тому для скопіювання своїх рядків у спільній тестовій базі
всюди нижче звужуємо саме за унікальним `last_name`.
"""
from tests.support.rbac import grant_role
import re
from datetime import datetime, timezone
from uuid import uuid4

from flask import url_for
import pytest

from app.extensions import db
from app.models.meta_lead import MetaLead
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'mpf-{_uid()}@test.com', 'password123',
        first_name='M', last_name='P', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


def _lead(platform, last_name, is_test=False):
    lead = MetaLead(
        leadgen_id=f'mpf-{_uid()}', created_time=datetime.now(timezone.utc),
        first_name='Лід', last_name=last_name, platform=platform, is_test=is_test,
    )
    db.session.add(lead)
    db.session.commit()
    return lead


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def _row_for(html, marker):
    """Рядок <tr>...</tr>, що містить marker -- щоб не зачепити чужі рядки
    спільної тестової бази.

    Шукаємо ЛИШЕ в `<tbody>`: заголовок таблиці несе посилання серверного
    сортування з тим самим `q=marker` у href (`sort_th` тягне поточні
    фільтри), тож без цього відсічення перший збіг marker траплявся б у
    заголовку, а не в рядку даних.
    """
    body = html.split('<tbody>', 1)[-1]
    m = re.search(
        rf'<tr>((?:(?!</tr>).)*{re.escape(marker)}(?:(?!</tr>).)*)</tr>',
        body, re.DOTALL,
    )
    assert m, f'рядок з {marker!r} не знайдено'
    return m.group(1)


@pytest.fixture
def leads(app):
    """Лід поза випадною підказкою ('msg') і лід у ній ('fb'), обидва
    знаходяться за спільним групуючим токеном у last_name."""
    group = _uid()
    outside = _lead('msg', f'{group}-outside')
    fb = _lead('fb', f'{group}-fb')
    yield group, outside, fb
    db.session.rollback()
    db.session.delete(db.session.merge(outside))
    db.session.delete(db.session.merge(fb))
    db.session.commit()


def test_platform_outside_dropdown_still_narrows(client, admin, leads):
    group, outside, fb = leads
    _login(client, admin)
    html = client.get(f'/admin/meta-leads?platform=msg&q={group}').get_data(as_text=True)
    assert outside.last_name in html
    assert fb.last_name not in html


def test_platform_outside_dropdown_shows_raw_value_in_chip(client, admin, leads):
    """Плашка активного фільтра лишається з підписом -- fallback на сире
    значення в `_filter_bar.html` спрацьовує, коли жодна опція `<select>`
    не збіглась зі значенням у URL."""
    group, outside, _fb = leads
    _login(client, admin)
    html = client.get(f'/admin/meta-leads?platform=msg&q={group}').get_data(as_text=True)
    assert re.search(r'<span class="admin-chip__key">Платформа:</span>\s*msg', html)


@pytest.mark.parametrize('junk', ['', '   ', 'x' * 11])
def test_junk_platform_behaves_as_no_filter(client, admin, leads, junk):
    group, outside, fb = leads
    _login(client, admin)
    resp = client.get(f'/admin/meta-leads?platform={junk}&q={group}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert outside.last_name in html
    assert fb.last_name in html


def test_request_without_platform_param_unchanged(client, admin, leads):
    group, outside, fb = leads
    _login(client, admin)
    html = client.get(f'/admin/meta-leads?q={group}').get_data(as_text=True)
    assert outside.last_name in html
    assert fb.last_name in html


def test_platform_label_links_to_own_filter_with_test_with(client, admin, app):
    """Мітка платформи в реєстрі -- посилання на цей самий реєстр, звужений
    `platform`, і несе `test='with'`: тестові заявки сховані за
    замовчуванням (`_leads_query`), і без цього параметра клік із тестового
    ліда приземлявся б у зрізі, де сам же лід відфільтрований."""
    last_name = f'mpf-link-{_uid()}'
    lead = _lead('msg', last_name, is_test=True)
    _login(client, admin)
    try:
        html = client.get(f'/admin/meta-leads?q={last_name}&test=with').get_data(as_text=True)
        row = _row_for(html, last_name)
        with app.test_request_context():
            href = url_for('admin.meta_leads_list', platform='msg', test='with')
        # Jinja екранує '&' у href як '&amp;' -- порівнюємо з HTML, а не з
        # сирим результатом url_for.
        href_html = href.replace('&', '&amp;')
        assert re.search(rf'<a href="{re.escape(href_html)}">\s*msg\s*</a>', row)
    finally:
        db.session.delete(db.session.merge(lead))
        db.session.commit()


def test_platform_label_without_value_stays_plain_text(client, admin, app):
    last_name = f'mpf-empty-{_uid()}'
    lead = _lead(None, last_name)
    _login(client, admin)
    try:
        html = client.get(f'/admin/meta-leads?q={last_name}').get_data(as_text=True)
        row = _row_for(html, last_name)
        m = re.search(r'\xb7\s*(<a[^>]*>)?\s*[–-]', row)
        assert m, 'мітка платформи (порожнє значення) не знайдена в рядку'
        assert m.group(1) is None, 'порожня платформа не має бути посиланням'
    finally:
        db.session.delete(db.session.merge(lead))
        db.session.commit()
