"""Презентації до заходів у кабінеті тренера: сторінка, завантаження, видалення."""
import io
import tempfile

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.trainer_presentation import TrainerPresentation
from app.services import trainer_links
from app.services import trainer_presentation_service as tps
from app.services.email_service import EmailService
from tests.test_trainer_cabinet._factories import (
    login, make_course, make_instance, make_trainer, make_user)

PDF = b'%PDF-1.7\n' + b'slides' * 50


@pytest.fixture(autouse=True)
def folder(app):
    prev = app.config['TRAINER_PRESENTATION_FOLDER']
    app.config['TRAINER_PRESENTATION_FOLDER'] = tempfile.mkdtemp()
    yield
    app.config['TRAINER_PRESENTATION_FOLDER'] = prev


@pytest.fixture
def sent(monkeypatch):
    """Лист співробітникам -- підмінений: тут перевіряється, що маршрут його
    кличе, а сам лист -- у test_presentation_notify."""
    calls = []

    def fake(presentation):
        calls.append(presentation.id)
        return [object()]

    monkeypatch.setattr(EmailService, 'send_trainer_presentation_notification',
                        staticmethod(fake))
    return calls


def _setup(client, days=7):
    user = make_user()
    trainer = make_trainer(user)
    instance = make_instance(make_course(title='Курс презентацій'), days=days)
    trainer_links.set_trainers(instance, [trainer.id])
    db.session.commit()
    login(client, user)
    return trainer, instance


def _upload(client, instance, data=PDF, name='Доповідь.pdf'):
    return client.post(f'/trainer/presentations/{instance.id}/upload',
                       data={'file': (io.BytesIO(data), name)},
                       content_type='multipart/form-data')


def test_page_lists_upcoming_events_with_an_upload_form(client):
    _trainer, instance = _setup(client)
    html = client.get('/trainer/presentations').get_data(as_text=True)
    assert 'Курс презентацій' in html
    assert f'/trainer/presentations/{instance.id}/upload' in html
    assert 'enctype="multipart/form-data"' in html
    assert f'accept="{tps.ACCEPT_ATTR}"' in html


def test_upload_saves_file_notifies_staff_and_marks_notified(client, sent):
    trainer, instance = _setup(client)
    resp = _upload(client, instance)
    assert resp.status_code == 302
    pres = TrainerPresentation.query.filter_by(trainer_id=trainer.id).one()
    assert pres.instance_id == instance.id
    assert tps.file_path(pres).read_bytes() == PDF
    assert sent == [pres.id]
    assert pres.notified_at is not None

    html = client.get('/trainer/presentations').get_data(as_text=True)
    assert 'Доповідь.pdf' in html


def test_upload_survives_mail_failure(client, monkeypatch):
    """Збій пошти не скасовує завантаження: файл лишається, notified_at --
    порожній (видно в адмінці, що лист не пішов)."""
    def boom(_p):
        raise RuntimeError('smtp down')
    monkeypatch.setattr(EmailService, 'send_trainer_presentation_notification',
                        staticmethod(boom))
    trainer, instance = _setup(client)
    assert _upload(client, instance).status_code == 302
    pres = TrainerPresentation.query.filter_by(trainer_id=trainer.id).one()
    assert pres.notified_at is None
    assert tps.file_path(pres).exists()


def test_rejected_file_is_not_saved(client, sent):
    trainer, instance = _setup(client)
    resp = _upload(client, instance, data=b'MZ' + b'x' * 50, name='fake.pdf')
    assert resp.status_code == 302
    assert TrainerPresentation.query.filter_by(trainer_id=trainer.id).count() == 0
    assert sent == []


def test_foreign_event_is_404(client, sent):
    _setup(client)
    other = make_instance(make_course())
    trainer_links.set_trainers(other, [make_trainer(name='Чужий Т.').id])
    db.session.commit()
    assert _upload(client, other).status_code == 404
    assert TrainerPresentation.query.filter_by(instance_id=other.id).count() == 0


def test_past_event_does_not_accept_uploads(client, sent):
    trainer, instance = _setup(client, days=-30)
    resp = _upload(client, instance)
    assert resp.status_code == 302
    assert TrainerPresentation.query.filter_by(trainer_id=trainer.id).count() == 0


def test_trainer_deletes_own_presentation(client, sent):
    trainer, instance = _setup(client)
    _upload(client, instance)
    pres = TrainerPresentation.query.filter_by(trainer_id=trainer.id).one()
    path = tps.file_path(pres)
    resp = client.post(f'/trainer/presentations/file/{pres.id}/delete')
    assert resp.status_code == 302
    assert db.session.get(TrainerPresentation, pres.id) is None
    assert not path.exists()


def test_cannot_delete_someone_elses_presentation(client, sent):
    trainer, instance = _setup(client)
    other_trainer = make_trainer(name='Інший Т.')
    other, _ = tps.save_upload(other_trainer, instance,
                               FileStorage(stream=io.BytesIO(PDF), filename='x.pdf'),
                               uploader=None)
    db.session.commit()
    assert client.post(f'/trainer/presentations/file/{other.id}/delete').status_code == 404
    assert db.session.get(TrainerPresentation, other.id) is not None


def test_profile_has_the_upload_button(client):
    _setup(client)
    html = client.get('/trainer/profile').get_data(as_text=True)
    assert 'href="/trainer/presentations"' in html


def test_upload_route_allows_bodies_above_the_global_limit(app):
    """Глобальні 25 МБ -- для фото; презентація має свою межу, і діяти вона
    мусить уже на розборі форми (до CSRF), тобто в класі запиту."""
    limit = app.config['TRAINER_PRESENTATION_MAX_BYTES']
    assert limit > app.config['MAX_CONTENT_LENGTH']
    with app.test_request_context('/trainer/presentations/1/upload', method='POST'):
        from flask import request
        assert request.max_content_length >= limit
    with app.test_request_context('/trainer/profile', method='POST'):
        from flask import request
        assert request.max_content_length == app.config['MAX_CONTENT_LENGTH']
