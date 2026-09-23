"""PDF-резюме тренерів."""
import pytest

from app.extensions import db
from tests.support.rbac import make_super_admin, switch_user
from tests.test_trainer_cabinet._factories import make_trainer


def _weasyprint_available():
    try:
        import weasyprint  # noqa: F401
    except Exception:
        return False
    return True


# Тест «відповідь починається з %PDF» має сенс лише при справжньому рендері
# (як у test_offer_pdf.py) -- на машині без GTK WeasyPrint не імпортується.
requires_weasyprint = pytest.mark.skipif(
    not _weasyprint_available(), reason='WeasyPrint недоступний (немає GTK)')


def _admin(client):
    admin = make_super_admin(email='tc-resume-admin@test.com')
    db.session.commit()
    switch_user(client, admin)
    return admin


@requires_weasyprint
def test_export_returns_pdf(client):
    _admin(client)
    trainer = make_trainer(name='Експортний Т.')
    db.session.commit()
    resp = client.post('/admin/trainers/resume.pdf', data={
        'ids': [str(trainer.id)],
        'columns': ['full_name', 'workplace'],
    })
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.data[:4] == b'%PDF'
    assert resp.headers['Cache-Control'] == 'no-store, private'


def test_export_without_ids_redirects(client):
    _admin(client)
    resp = client.post('/admin/trainers/resume.pdf', data={'ids': []})
    assert resp.status_code == 302


def test_export_requires_permission(client):
    from tests.test_trainer_cabinet._factories import login, make_user

    login(client, make_user())
    resp = client.post('/admin/trainers/resume.pdf', data={'ids': ['1']})
    assert resp.status_code in (302, 403, 404)


@requires_weasyprint
def test_unknown_column_is_ignored(client):
    _admin(client)
    trainer = make_trainer(name='Колонковий Т.')
    db.session.commit()
    resp = client.post('/admin/trainers/resume.pdf', data={
        'ids': [str(trainer.id)],
        'columns': ['full_name', 'fop_iban'],
    })
    assert resp.status_code == 200
    assert resp.data[:4] == b'%PDF'


@requires_weasyprint
def test_rows_follow_request_order_not_db_order(client):
    """Порядок рядків -- як у запиті, а не як віддала БД.

    Без сортування за id тренер, доданий пізніше, лежав би в БД раніше за
    того, що з меншим id, і документ мовчки переставляв би рядки місцями
    щодо порядку, в якому адмін обирав тренерів у поданні заходу.
    """
    _admin(client)
    first = make_trainer(name='Перший Т.')
    second = make_trainer(name='Другий Т.')
    db.session.commit()

    from app.services import trainer_resume_service as rs
    calls = []
    original = rs.build_rows

    def spy(trainers, keys):
        calls.append([t.id for t in trainers])
        return original(trainers, keys)

    rs.build_rows = spy
    try:
        resp = client.post('/admin/trainers/resume.pdf', data={
            'ids': [str(second.id), str(first.id)],
            'columns': ['full_name'],
        })
    finally:
        rs.build_rows = original

    assert resp.status_code == 200
    assert calls == [[second.id, first.id]]
