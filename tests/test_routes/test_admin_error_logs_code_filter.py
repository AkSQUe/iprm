"""`error_code` у журналі помилок приймає будь-який HTTP-статус.

`ErrorLog.error_code` -- будь-яке ціле (`getattr(exception, 'code', 500)` у
`app/models/error_log.py`), а не лише вісім кодів із випадної підказки.
Раніше фільтр звіряв значення проти фіксованого кортежу (`choice_arg`), тож
код на кшталт 502 мовчки не звужував нічого -- адмін бачив невідфільтрований
журнал, вважаючи його звуженим.
"""
import re
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.error_log import ErrorLog
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'ecf-{_uid()}@test.com', 'password123',
        first_name='E', last_name='C', is_admin=True, email_confirmed=True,
    )
    # commit, а не flush: сторінка журналу починається з захисного
    # db.session.rollback(), який зніс би незакомічені рядки.
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


@pytest.fixture
def logs(app):
    """502, якого нема у випадній підказці, і 404, який там є."""
    bad_gateway = ErrorLog(
        error_code=502, error_type='BadGateway', error_message=f'lost-{_uid()}',
        url='/upstream/timeout', method='GET',
    )
    not_found = ErrorLog(
        error_code=404, error_type='NotFound', error_message=f'missing-{_uid()}',
        url='/courses/missing', method='GET',
    )
    db.session.add_all([bad_gateway, not_found])
    db.session.commit()
    yield bad_gateway, not_found
    db.session.rollback()
    db.session.delete(db.session.merge(bad_gateway))
    db.session.delete(db.session.merge(not_found))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_code_outside_dropdown_still_narrows(client, admin, logs):
    bad_gateway, not_found = logs
    _login(client, admin)
    html = client.get('/admin/error-logs?error_code=502&days=0').get_data(as_text=True)
    assert bad_gateway.error_message in html
    assert not_found.error_message not in html


@pytest.mark.parametrize('junk', ['abc', '99', '700', ''])
def test_junk_code_behaves_as_no_filter(client, admin, logs, junk):
    _login(client, admin)
    resp = client.get(f'/admin/error-logs?error_code={junk}&days=0')
    assert resp.status_code == 200
    bad_gateway, not_found = logs
    html = resp.get_data(as_text=True)
    assert bad_gateway.error_message in html
    assert not_found.error_message in html


def test_code_outside_dropdown_narrows_export_too(client, admin, logs):
    """Фільтр спільний зі сторінкою -- код 502 звужує і xlsx-експорт."""
    import io

    from openpyxl import load_workbook

    bad_gateway, not_found = logs
    _login(client, admin)
    r = client.get('/admin/error-logs/export?error_code=502&days=0')
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.data))
    ws = wb['Помилки']
    messages = [
        ws.cell(row=row, column=col).value
        for row in range(2, ws.max_row + 1)
        for col in range(1, ws.max_column + 1)
    ]
    assert bad_gateway.error_message in messages
    assert not_found.error_message not in messages


def test_code_outside_dropdown_shows_in_chip(client, admin, logs):
    """Чіпс активного фільтра лишається з підписом, а не порожній «Код: »."""
    _login(client, admin)
    html = client.get('/admin/error-logs?error_code=502&days=0').get_data(as_text=True)
    assert re.search(r'<span class="admin-chip__key">Код:</span>\s*502', html)
