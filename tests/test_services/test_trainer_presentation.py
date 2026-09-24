"""Презентації тренерів до заходів: збереження, перевірка файлу, адресати."""
import io
import os
import re
import tempfile
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.trainer_presentation import TrainerPresentation
from app.services import trainer_presentation_service as tps
from tests.support.rbac import make_user_with_role
from tests.test_trainer_cabinet._factories import make_course, make_instance, make_trainer

PDF = b'%PDF-1.7\n' + b'x' * 100
PPTX = b'PK\x03\x04' + b'x' * 100
PPT = bytes.fromhex('D0CF11E0A1B11AE1') + b'x' * 100


@pytest.fixture(autouse=True)
def folder(app):
    prev = app.config['TRAINER_PRESENTATION_FOLDER']
    app.config['TRAINER_PRESENTATION_FOLDER'] = tempfile.mkdtemp()
    yield Path(app.config['TRAINER_PRESENTATION_FOLDER'])
    app.config['TRAINER_PRESENTATION_FOLDER'] = prev


def _file(data, name):
    return FileStorage(stream=io.BytesIO(data), filename=name)


def _event():
    trainer = make_trainer(name='Презентер П.')
    instance = make_instance(make_course())
    return trainer, instance


@pytest.mark.parametrize('data,name,mimetype', [
    (PDF, 'Доповідь.pdf', 'application/pdf'),
    (PPTX, 'slides.PPTX',
     'application/vnd.openxmlformats-officedocument.presentationml.presentation'),
    (PPT, 'old.ppt', 'application/vnd.ms-powerpoint'),
])
def test_accepted_formats_are_stored_byte_for_byte(app, folder, data, name, mimetype):
    trainer, instance = _event()
    pres, error = tps.save_upload(trainer, instance, _file(data, name), uploader=None)
    assert error is None
    db.session.commit()

    assert pres.original_filename == name
    assert pres.mimetype == mimetype
    assert pres.size_bytes == len(data)
    assert tps.file_path(pres).read_bytes() == data


def test_stored_name_is_random_and_never_taken_from_the_client(app, folder):
    """Ім'я клієнта в шляху файлової системи -- обхід каталогу."""
    trainer, instance = _event()
    pres, error = tps.save_upload(trainer, instance, _file(PDF, '../../evil.pdf'),
                                  uploader=None)
    assert error is None
    assert re.fullmatch(r'[0-9a-f]{32}\.pdf', pres.stored_name)
    path = tps.file_path(pres).resolve()
    assert folder.resolve() in path.parents


@pytest.mark.parametrize('data,name', [
    (b'MZ\x90\x00' + b'x' * 50, 'virus.pdf'),     # розширення бреше
    (PDF, 'script.exe'),                          # недозволене розширення
    (PDF, 'no-extension'),
    (b'', 'empty.pdf'),
])
def test_rejects_wrong_or_lying_files(app, folder, data, name):
    trainer, instance = _event()
    pres, error = tps.save_upload(trainer, instance, _file(data, name), uploader=None)
    assert pres is None and error
    assert list(folder.rglob('*')) == [] or all(p.is_dir() for p in folder.rglob('*'))


def test_rejects_file_over_the_limit(app, folder):
    trainer, instance = _event()
    prev = app.config['TRAINER_PRESENTATION_MAX_BYTES']
    app.config['TRAINER_PRESENTATION_MAX_BYTES'] = 50
    try:
        pres, error = tps.save_upload(trainer, instance, _file(PDF, 'big.pdf'), uploader=None)
    finally:
        app.config['TRAINER_PRESENTATION_MAX_BYTES'] = prev
    assert pres is None and 'МБ' in error


def test_delete_removes_row_and_file(app, folder):
    trainer, instance = _event()
    pres, _ = tps.save_upload(trainer, instance, _file(PDF, 'a.pdf'), uploader=None)
    db.session.commit()
    path = tps.file_path(pres)
    assert path.exists()

    tps.delete(pres)
    assert not path.exists()
    assert db.session.get(TrainerPresentation, pres.id) is None


def test_discard_file_after_failed_commit(app, folder):
    """Рядок не закомітився -- файл на диску не повинен лишитись сиротою."""
    trainer, instance = _event()
    pres, _ = tps.save_upload(trainer, instance, _file(PDF, 'a.pdf'), uploader=None)
    path = tps.file_path(pres)
    db.session.rollback()
    tps.discard_file(pres)
    assert not path.exists()


def test_recipients_are_staff_with_the_three_roles(app):
    super_admin = make_user_with_role('super_admin', email='tp-sa@test.com')
    admin = make_user_with_role('admin', email='tp-admin@test.com')
    editor = make_user_with_role('content_editor', email='tp-editor@test.com')
    make_user_with_role('manager', email='tp-manager@test.com')
    make_user_with_role('marketer', email='tp-marketer@test.com')
    inactive = make_user_with_role('admin', email='tp-inactive@test.com')
    inactive.is_active = False
    db.session.commit()

    emails = tps.recipient_emails()
    assert {'tp-sa@test.com', 'tp-admin@test.com', 'tp-editor@test.com'} <= set(emails)
    assert 'tp-manager@test.com' not in emails
    assert 'tp-marketer@test.com' not in emails
    assert 'tp-inactive@test.com' not in emails
    assert len(emails) == len(set(e.lower() for e in emails))
    assert super_admin and admin and editor


def test_deploy_does_not_wipe_the_presentation_folder():
    """rsync --delete без exclude стирав би всі завантажені презентації
    на кожному деплої -- і зовні це не виглядало б поламаним."""
    workflow = (Path(__file__).resolve().parents[2] / '.github' / 'workflows'
                / 'deploy.yml').read_text(encoding='utf-8')
    assert "--exclude='/trainer_presentations/'" in workflow
    from config import Config
    assert os.path.basename(Config.TRAINER_PRESENTATION_FOLDER) == 'trainer_presentations'
