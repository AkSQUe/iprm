"""Retention і застряглі операції: два способи втратити бекапи молча.

Обидва сценарії тут не вигадані -- відтворені на живому коді до правки:
очищення зносило ОСТАННЮ копію, а рядок, що застряг у in_progress після
перезапуску воркера, назавжди блокував усі наступні спроби.
"""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.database_backup import DatabaseBackup
from app.models.mixins import utcnow
from app.services.backup_service import (
    BackupService, BackupConcurrencyError,
)

PG_URL = 'postgresql://user:pass@localhost:5432/testdb'


@pytest.fixture(autouse=True)
def clean_slate():
    """Таблиця копій спільна на сесію -- чужі рядки зіпсували б арифметику."""
    DatabaseBackup.query.delete()
    db.session.commit()
    yield


@pytest.fixture
def pg_env(app, monkeypatch):
    monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', PG_URL)
    monkeypatch.setattr('shutil.which', lambda name: f'/usr/bin/{name}')


def _backup(days_ago, status=DatabaseBackup.STATUS_COMPLETED,
            backup_type=DatabaseBackup.TYPE_FULL, name=None):
    backup = DatabaseBackup(
        filename=name or f'backup_{days_ago}d.dump',
        file_path=f'/nonexistent/backup_{days_ago}d_{status}.dump',
        file_size_bytes=1024,
        backup_type=backup_type,
        status=status,
        checksum_sha256='f' * 64,
        created_at=utcnow() - timedelta(days=days_ago),
    )
    db.session.add(backup)
    db.session.commit()
    return backup


class TestRetentionFloor:
    """Скільки б не минуло часу, якась кількість копій мусить лишитись."""

    def test_last_copy_survives_retention(self, app):
        """Найгірший випадок: усі копії старші за retention.

        Місяць без нових бекапів -- і очищення лишало НУЛЬ копій саме тоді,
        коли вони найпотрібніші.
        """
        _backup(days_ago=99)

        BackupService.cleanup_old_backups()

        assert DatabaseBackup.query.count() == 1

    def test_keeps_the_configured_minimum(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'BACKUP_MIN_KEEP', 3)
        for day in (99, 98, 97, 96, 95):
            _backup(days_ago=day)

        result = BackupService.cleanup_old_backups()

        assert DatabaseBackup.query.count() == 3
        assert result['deleted'] == 2

    def test_newest_copies_are_the_ones_kept(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'BACKUP_MIN_KEEP', 2)
        _backup(days_ago=99, name='oldest.dump')
        _backup(days_ago=50, name='middle.dump')
        _backup(days_ago=40, name='newest.dump')

        BackupService.cleanup_old_backups()

        survivors = {b.filename for b in DatabaseBackup.query.all()}
        assert survivors == {'middle.dump', 'newest.dump'}

    def test_fresh_copies_are_never_touched(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'BACKUP_RETENTION_DAYS', 30)
        monkeypatch.setitem(app.config, 'BACKUP_MIN_KEEP', 1)
        _backup(days_ago=1)
        _backup(days_ago=2)

        result = BackupService.cleanup_old_backups()

        assert result['deleted'] == 0
        assert DatabaseBackup.query.count() == 2

    def test_dry_run_respects_the_floor(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'BACKUP_MIN_KEEP', 2)
        for day in (99, 98, 97):
            _backup(days_ago=day)

        result = BackupService.cleanup_old_backups(dry_run=True)

        assert result['would_delete'] == 1
        assert DatabaseBackup.query.count() == 3, 'dry run нічого не видаляє'


class TestStuckOperations:
    """Рядок у in_progress після аварії воркера не має блокувати систему."""

    def test_stale_row_does_not_block_new_backup(self, app, pg_env, monkeypatch):
        """Перезапуск gunicorn посеред дампу лишав рядок in_progress назавжди.

        BACKUP_MAX_CONCURRENT=1, реапера не було -- і кожна наступна копія
        падала з BackupConcurrencyError. Бекапи вмирали молча вдруге.
        """
        _backup(days_ago=30, status=DatabaseBackup.STATUS_IN_PROGRESS)
        calls = []
        monkeypatch.setattr(
            'subprocess.run',
            lambda *a, **kw: calls.append(a) or _FakeCompleted(),
        )
        monkeypatch.setattr('os.path.getsize', lambda path: 2048)
        monkeypatch.setattr(
            BackupService, '_compute_checksum', classmethod(lambda cls, p: 'a' * 64),
        )

        BackupService.create_backup()

        assert calls, 'pg_dump мусив запуститись'

    def test_stale_row_is_marked_failed(self, app):
        stale = _backup(days_ago=30, status=DatabaseBackup.STATUS_IN_PROGRESS)

        BackupService.reap_stuck_backups()

        db.session.refresh(stale)
        assert stale.status == DatabaseBackup.STATUS_FAILED
        assert 'перерв' in (stale.error_message or '').lower()

    def test_running_backup_is_left_alone(self, app):
        """Копія, що триває просто зараз, реапером не чіпається."""
        fresh = _backup(days_ago=0, status=DatabaseBackup.STATUS_IN_PROGRESS)

        BackupService.reap_stuck_backups()

        db.session.refresh(fresh)
        assert fresh.status == DatabaseBackup.STATUS_IN_PROGRESS

    def test_concurrency_guard_still_holds_for_live_operation(self, app, pg_env):
        _backup(days_ago=0, status=DatabaseBackup.STATUS_IN_PROGRESS)

        with pytest.raises(BackupConcurrencyError):
            BackupService.create_backup()


class _FakeCompleted:
    returncode = 0
    stdout = ''
    stderr = ''
