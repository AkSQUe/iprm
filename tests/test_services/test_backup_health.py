"""Тривоги сховища копій: місце на диску і вік останньої копії.

Ця система вже один раз простояла мертвою три місяці саме тому, що
ламалась молча. Тому стан сховища мусить бути видимим НА СТОРІНЦІ, а не
лише в журналі, який ніхто не читає.
"""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.database_backup import DatabaseBackup
from app.models.mixins import utcnow
from app.services.backup_service import BackupService


@pytest.fixture(autouse=True)
def clean_slate(app):
    DatabaseBackup.query.delete()
    db.session.commit()
    yield


def _completed(hours_ago):
    backup = DatabaseBackup(
        filename=f'b_{hours_ago}.dump',
        file_path=f'/nonexistent/b_{hours_ago}.dump',
        file_size_bytes=1024,
        backup_type=DatabaseBackup.TYPE_FULL,
        status=DatabaseBackup.STATUS_COMPLETED,
        checksum_sha256='a' * 64,
        created_at=utcnow() - timedelta(hours=hours_ago),
    )
    db.session.add(backup)
    db.session.commit()
    return backup


def _fake_disk(monkeypatch, free_ratio):
    """Підмінити показники диска: total 100 ГБ, вільно -- задана частка."""
    total = 100 * 1024 ** 3

    class _Usage:
        pass

    usage = _Usage()
    usage.total = total
    usage.used = int(total * (1 - free_ratio))
    usage.free = int(total * free_ratio)
    monkeypatch.setattr(
        'shutil.disk_usage',
        lambda path: (usage.total, usage.used, usage.free),
    )


class TestStaleBackupAlarm:

    def test_fresh_copy_is_not_stale(self, app, monkeypatch):
        _fake_disk(monkeypatch, free_ratio=0.5)
        _completed(hours_ago=2)

        assert BackupService.get_storage_stats()['is_stale'] is False

    def test_old_copy_raises_the_alarm(self, app, monkeypatch):
        _fake_disk(monkeypatch, free_ratio=0.5)
        _completed(hours_ago=100)

        assert BackupService.get_storage_stats()['is_stale'] is True

    def test_no_copies_at_all_is_stale(self, app, monkeypatch):
        """Нуль копій -- найтривожніший стан, а не нейтральний."""
        _fake_disk(monkeypatch, free_ratio=0.5)

        assert BackupService.get_storage_stats()['is_stale'] is True

    def test_threshold_comes_from_config(self, app, monkeypatch):
        _fake_disk(monkeypatch, free_ratio=0.5)
        monkeypatch.setitem(app.config, 'BACKUP_MAX_AGE_HOURS', 200)
        _completed(hours_ago=100)

        assert BackupService.get_storage_stats()['is_stale'] is False


class TestDiskSpaceAlarm:

    def test_plenty_of_space_is_quiet(self, app, monkeypatch):
        _fake_disk(monkeypatch, free_ratio=0.5)

        stats = BackupService.get_storage_stats()

        assert stats['disk_low'] is False
        assert stats['disk_free_percent'] == 50

    def test_low_space_raises_the_alarm(self, app, monkeypatch):
        """Повний диск кладе ВЕСЬ сайт, не лише копії."""
        _fake_disk(monkeypatch, free_ratio=0.04)

        stats = BackupService.get_storage_stats()

        assert stats['disk_low'] is True
        assert stats['disk_free_percent'] == 4

    def test_threshold_comes_from_config(self, app, monkeypatch):
        _fake_disk(monkeypatch, free_ratio=0.2)
        monkeypatch.setitem(app.config, 'BACKUP_DISK_FREE_MIN_PERCENT', 30)

        assert BackupService.get_storage_stats()['disk_low'] is True


class TestConsistentUnits:
    """Картки і таблиця мусять рахувати розмір однаково."""

    def test_stats_carry_ready_made_display_strings(self, app, monkeypatch):
        """Шаблон брав filesizeformat (ділить на 1000), а таблиця --
        file_size_display (ділить на 1024): той самий файл показувався
        двома різними числами."""
        _fake_disk(monkeypatch, free_ratio=0.5)
        _completed(hours_ago=1)

        stats = BackupService.get_storage_stats()

        assert stats['total_size_display'] == '1.0 KB'
        assert stats['disk_free_display'] == '50.0 GB'
