"""Лист співробітникам про презентацію тренера й завантаження її в адмінці."""
import io
import tempfile

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.email_log import EmailLog
from app.services import trainer_presentation_service as tps
from app.services.email_service import EmailService
from tests.support.mail import enable_live_mail
from tests.support.rbac import make_user_with_role, switch_user
from tests.test_trainer_cabinet._factories import make_course, make_instance, make_trainer

PDF = b'%PDF-1.7\n' + b'slides' * 50


@pytest.fixture(autouse=True)
def folder(app):
    prev = app.config['TRAINER_PRESENTATION_FOLDER']
    app.config['TRAINER_PRESENTATION_FOLDER'] = tempfile.mkdtemp()
    yield
    app.config['TRAINER_PRESENTATION_FOLDER'] = prev


def _presentation(name='Доповідь.pdf'):
    trainer = make_trainer(name='Лекторенко Л. Л.')
    course = make_course(title='Плазмотерапія в дерматології')
    instance = make_instance(course)
    pres, error = tps.save_upload(
        trainer, instance, FileStorage(stream=io.BytesIO(PDF), filename=name), uploader=None)
    assert error is None
    db.session.commit()
    return pres


def test_email_goes_to_each_staff_role_and_links_the_admin_download(app, monkeypatch):
    enable_live_mail(monkeypatch)
    make_user_with_role('super_admin', email='tpn-sa@test.com')
    make_user_with_role('admin', email='tpn-admin@test.com')
    make_user_with_role('content_editor', email='tpn-editor@test.com')
    make_user_with_role('manager', email='tpn-manager@test.com')
    db.session.commit()
    pres = _presentation()

    with app.test_request_context():
        results = EmailService.send_trainer_presentation_notification(pres)

    logs = EmailLog.query.filter_by(trigger='trainer_presentation').all()
    to = {log.to_email for log in logs}
    assert {'tpn-sa@test.com', 'tpn-admin@test.com', 'tpn-editor@test.com'} <= to
    assert 'tpn-manager@test.com' not in to
    assert any(r is not None for r in results)
    log = next(log for log in logs if log.to_email == 'tpn-editor@test.com')
    assert 'Лекторенко Л. Л.' in log.subject
    assert f'/admin/trainers/presentations/{pres.id}/download' in (log.html_body or '')
    # Посилання, а не вкладення: файл до 50 МБ пошта не пропустила б.
    assert not log.attachments


def test_repeat_call_for_the_same_upload_does_not_duplicate(app, monkeypatch):
    enable_live_mail(monkeypatch)
    make_user_with_role('admin', email='tpn-once@test.com')
    db.session.commit()
    pres = _presentation()
    with app.test_request_context():
        EmailService.send_trainer_presentation_notification(pres)
        EmailService.send_trainer_presentation_notification(pres)
    assert EmailLog.query.filter_by(trigger='trainer_presentation',
                                    to_email='tpn-once@test.com').count() == 1


def test_admin_download_returns_the_exact_file(client):
    pres = _presentation('Слайди ІПРМ.pdf')
    editor = make_user_with_role('content_editor', email='tpn-dl-editor@test.com')
    db.session.commit()
    switch_user(client, editor)

    resp = client.get(f'/admin/trainers/presentations/{pres.id}/download')
    assert resp.status_code == 200
    assert resp.data == PDF
    assert resp.mimetype == 'application/pdf'
    assert 'attachment' in resp.headers['Content-Disposition']
    assert 'no-store' in resp.headers['Cache-Control']


def test_admin_download_is_closed_without_trainers_view(client):
    pres = _presentation()
    marketer = make_user_with_role('marketer', email='tpn-dl-marketer@test.com')
    db.session.commit()
    switch_user(client, marketer)
    resp = client.get(f'/admin/trainers/presentations/{pres.id}/download')
    assert resp.status_code in (302, 403, 404)
    assert resp.data != PDF


def test_admin_download_of_missing_file_is_404(client):
    pres = _presentation()
    tps.file_path(pres).unlink()
    admin = make_user_with_role('admin', email='tpn-dl-missing@test.com')
    db.session.commit()
    switch_user(client, admin)
    assert client.get(f'/admin/trainers/presentations/{pres.id}/download').status_code == 404


def test_instance_page_lists_presentations_with_download_links(client):
    pres = _presentation('Слайди до заходу.pdf')
    admin = make_user_with_role('admin', email='tpn-inst-admin@test.com')
    db.session.commit()
    switch_user(client, admin)
    html = client.get(f'/admin/instances/{pres.instance_id}/edit').get_data(as_text=True)
    assert 'Презентації тренерів' in html
    assert 'Слайди до заходу.pdf' in html
    assert f'/admin/trainers/presentations/{pres.id}/download' in html
    # Лист не пішов (notified_at порожній) -- це видно тут.
    assert 'Лист не надіслано' in html
