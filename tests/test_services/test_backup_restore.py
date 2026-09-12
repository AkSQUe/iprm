"""Відновлення з копії: чим воно має відмовлятись, а не вдавати успіх.

Відновлення живе лише в CLI (`flask backup restore`), і саме тому кожна його
відмова мусить бути гучною: людина біля консолі -- останній, хто може
зупинити втрату даних.
"""
import hashlib
import subprocess

import pytest

from app.extensions import db
from app.models.database_backup import DatabaseBackup
from app.services.backup_service import (
    BackupService, BackupError, BackupTimeoutError,
)

PG_URL = 'postgresql://user:pass@localhost:5432/testdb'


@pytest.fixture
def pg_env(app, monkeypatch):
    monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', PG_URL)
    monkeypatch.setattr('shutil.which', lambda name: f'/usr/bin/{name}')


@pytest.fixture
def restorable(tmp_path):
    """Справжній файл на диску з правильною контрольною сумою."""
    path = tmp_path / 'backup_full_20260912_030000.dump'
    path.write_bytes(b'PGDMP fake custom-format payload')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    backup = DatabaseBackup(
        filename=path.name,
        file_path=str(path),
        file_size_bytes=path.stat().st_size,
        backup_type=DatabaseBackup.TYPE_FULL,
        status=DatabaseBackup.STATUS_COMPLETED,
        checksum_sha256=digest,
    )
    db.session.add(backup)
    db.session.commit()
    return backup


@pytest.fixture
def no_pre_restore_copy(monkeypatch):
    """Запобіжна копія не створюється -- імітуємо збій під час неї."""
    def _boom(cls, **kwargs):
        raise BackupError('немає місця на диску')

    monkeypatch.setattr(BackupService, 'create_backup', classmethod(_boom))


def _fake_run(returncode=0, stderr=''):
    class _Completed:
        pass

    def _run(*args, **kwargs):
        result = _Completed()
        result.returncode = returncode
        result.stdout = ''
        result.stderr = stderr
        return result

    return _run


class TestFailureIsNeverReportedAsSuccess:

    def test_nonzero_exit_fails_even_with_warnings_in_stderr(
        self, pg_env, restorable, monkeypatch,
    ):
        """Умова `'WARNING' not in stderr` ковтала справжні збої.

        pg_restore друкує попередження майже завжди, тож провалене
        відновлення звітувало True і писало в лог "Backup restored" -- на
        зруйнованій базі.
        """
        monkeypatch.setattr(BackupService, 'create_backup',
                            classmethod(lambda cls, **kw: None))
        monkeypatch.setattr('subprocess.run', _fake_run(
            returncode=1,
            stderr='pg_restore: WARNING: errors ignored on restore: 12\n'
                   'pg_restore: error: could not execute query',
        ))

        with pytest.raises(BackupError) as exc:
            BackupService.restore_backup(restorable.id, force=True)

        assert 'could not execute query' in str(exc.value)

    def test_successful_restore_returns_true(self, pg_env, restorable, monkeypatch):
        monkeypatch.setattr('subprocess.run', _fake_run(returncode=0))

        assert BackupService.restore_backup(restorable.id, force=True) is True

    def test_timeout_is_its_own_error(self, pg_env, restorable, monkeypatch):
        def _timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd='pg_restore', timeout=1)

        monkeypatch.setattr('subprocess.run', _timeout)

        with pytest.raises(BackupTimeoutError):
            BackupService.restore_backup(restorable.id, force=True)


class TestSafetyNetIsMandatory:

    def test_restore_refuses_without_a_pre_restore_copy(
        self, pg_env, restorable, no_pre_restore_copy, monkeypatch,
    ):
        """Без страхувальної копії відновлення не починається.

        Раніше збій її створення лише писався в лог, а відновлення йшло
        далі -- тобто найнебезпечніша операція в системі лишалась без
        жодного шляху назад, і людина про це не знала.
        """
        ran = []
        monkeypatch.setattr('subprocess.run',
                            lambda *a, **kw: ran.append(a) or _fake_run()(*a, **kw))

        with pytest.raises(BackupError) as exc:
            BackupService.restore_backup(restorable.id)

        assert 'запобіжн' in str(exc.value).lower()
        assert ran == [], 'pg_restore не мусив навіть запуститись'

    def test_force_skips_the_net_deliberately(
        self, pg_env, restorable, no_pre_restore_copy, monkeypatch,
    ):
        """--force -- усвідомлена відмова від сітки, і вона має працювати."""
        monkeypatch.setattr('subprocess.run', _fake_run(returncode=0))

        assert BackupService.restore_backup(restorable.id, force=True) is True
