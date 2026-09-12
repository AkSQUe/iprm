"""Щоденна автоматична копія: поведінка при непридатному середовищі.

Тестується внутрішня функція, а не обгортка: обгортка бере
`pg_try_advisory_lock`, якого в SQLite немає -- той самий поділ, що й у
решти джоб планувальника.
"""
import logging

import pytest

from app.services import scheduler_service


@pytest.fixture
def notifications(monkeypatch):
    """Перехоплюємо сповіщення адмінам, щоб не ходити в SMTP."""
    sent = []
    monkeypatch.setattr(
        scheduler_service, '_notify_backup_failure', lambda message: sent.append(message),
    )
    return sent


def test_missing_pg_tools_logs_one_readable_line(app, monkeypatch, notifications, caplog):
    """Відома умова середовища -- це попередження, а не стектрейс.

    На проді бракувало postgresql-client, і джоба щоночі вивалювала в
    журнал два стектрейси: 490 рядків за два тижні, серед яких причину
    ніхто не шукав.
    """
    monkeypatch.setattr('shutil.which', lambda name: None)

    with caplog.at_level(logging.DEBUG, logger='app.services.scheduler_service'):
        scheduler_service._run_automatic_database_backup()

    records = [r for r in caplog.records if r.name == 'app.services.scheduler_service']
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None, 'стектрейс тут не потрібен'
    assert 'postgresql-client' in records[0].getMessage()


def test_missing_pg_tools_still_raises_the_alarm(app, monkeypatch, notifications):
    """Тихо пропускати не можна: мовчання і є причина трьох мертвих місяців."""
    monkeypatch.setattr('shutil.which', lambda name: None)

    scheduler_service._run_automatic_database_backup()

    assert len(notifications) == 1
    assert 'postgresql-client' in notifications[0]


class TestWeeklyIntegrityReport:
    """Тиша означала і «все добре», і «система мертва». Звіт розводить ці два."""

    @pytest.fixture
    def reports(self, monkeypatch):
        sent = []
        monkeypatch.setattr(
            scheduler_service, '_notify_backup_report',
            lambda stats, integrity: sent.append((stats, integrity)),
        )
        return sent

    def test_report_checks_every_copy(self, app, monkeypatch, reports):
        calls = []
        monkeypatch.setattr(
            'app.services.backup_service.BackupService.validate_all_backups',
            classmethod(lambda cls: calls.append(1) or {'checked': 4, 'corrupted': 0}),
        )

        scheduler_service._run_backup_integrity_report()

        assert calls, 'перевірка копій мусила виконатись'

    def test_report_carries_the_integrity_result(self, app, monkeypatch, reports):
        monkeypatch.setattr(
            'app.services.backup_service.BackupService.validate_all_backups',
            classmethod(lambda cls: {'checked': 3, 'corrupted': 1}),
        )

        scheduler_service._run_backup_integrity_report()

        assert len(reports) == 1
        _, integrity = reports[0]
        assert integrity == {'checked': 3, 'corrupted': 1}

    def test_report_carries_storage_state(self, app, monkeypatch, reports):
        monkeypatch.setattr(
            'app.services.backup_service.BackupService.validate_all_backups',
            classmethod(lambda cls: {'checked': 1, 'corrupted': 0}),
        )

        scheduler_service._run_backup_integrity_report()

        stats, _ = reports[0]
        assert 'is_stale' in stats
        assert 'disk_free_display' in stats


def test_healthy_environment_creates_the_copy(app, monkeypatch, notifications):
    calls = []

    class FakeBackup:
        filename = 'backup_full_20260912_030000.dump'
        file_size_display = '5.0 MB'
        duration_seconds = 3.2

    monkeypatch.setattr('shutil.which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr(
        'app.services.backup_service.BackupService.create_backup',
        classmethod(lambda cls, **kwargs: calls.append(kwargs) or FakeBackup()),
    )

    scheduler_service._run_automatic_database_backup()

    assert len(calls) == 1
    assert calls[0]['backup_type'] == 'full'
    assert notifications == []
