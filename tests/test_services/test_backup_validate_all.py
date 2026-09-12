"""Пакетна перевірка цілісності копій.

Поштучна перевірка знаходить гниль лише там, куди адмін сам клікнув. Копія
ж потрібна рівно один раз -- і саме тоді з'ясовується, що файл давно
побитий. Тому перевірку проганяють усю й регулярно.
"""
import hashlib

import pytest

from app.extensions import db
from app.models.database_backup import DatabaseBackup
from app.services.backup_service import BackupService


@pytest.fixture(autouse=True)
def clean_slate(app):
    DatabaseBackup.query.delete()
    db.session.commit()
    yield


def _healthy(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b'payload-' + name.encode())
    backup = DatabaseBackup(
        filename=name,
        file_path=str(path),
        file_size_bytes=path.stat().st_size,
        backup_type=DatabaseBackup.TYPE_FULL,
        status=DatabaseBackup.STATUS_COMPLETED,
        checksum_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    db.session.add(backup)
    db.session.commit()
    return backup


def _rotten(tmp_path, name):
    """Копія, файл якої змінився після зняття."""
    backup = _healthy(tmp_path, name)
    (tmp_path / name).write_bytes(b'corrupted beyond recognition')
    return backup


def test_all_completed_copies_are_checked(app, tmp_path):
    _healthy(tmp_path, 'a.dump')
    _healthy(tmp_path, 'b.dump')

    result = BackupService.validate_all_backups()

    assert result['checked'] == 2
    assert result['corrupted'] == 0


def test_rotten_copy_is_found_and_marked(app, tmp_path):
    good = _healthy(tmp_path, 'good.dump')
    bad = _rotten(tmp_path, 'bad.dump')

    result = BackupService.validate_all_backups()

    assert result['corrupted'] == 1
    db.session.refresh(bad)
    db.session.refresh(good)
    assert bad.status == DatabaseBackup.STATUS_CORRUPTED
    assert good.status == DatabaseBackup.STATUS_COMPLETED


def test_already_broken_copies_are_not_rechecked(app, tmp_path):
    """Перевіряємо лише те, на що ще можна покластися."""
    broken = _healthy(tmp_path, 'broken.dump')
    broken.status = DatabaseBackup.STATUS_FAILED
    db.session.commit()

    assert BackupService.validate_all_backups()['checked'] == 0


def test_empty_storage_is_not_an_error(app):
    assert BackupService.validate_all_backups() == {'checked': 0, 'corrupted': 0}


def test_one_unreadable_file_does_not_stop_the_pass(app, tmp_path, monkeypatch):
    """Збій на одній копії не має зривати перевірку решти."""
    _healthy(tmp_path, 'first.dump')
    _healthy(tmp_path, 'second.dump')
    real_validate = BackupService.validate_backup.__func__
    seen = []

    def _flaky(cls, backup_id):
        seen.append(backup_id)
        if len(seen) == 1:
            raise OSError('диск відмовив')
        return real_validate(cls, backup_id)

    monkeypatch.setattr(BackupService, 'validate_backup', classmethod(_flaky))

    result = BackupService.validate_all_backups()

    assert len(seen) == 2, 'друга копія мусила бути перевірена'
    assert result['checked'] == 1
