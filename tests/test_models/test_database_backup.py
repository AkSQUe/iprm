"""Модель DatabaseBackup: показ розмірів і статистика."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.database_backup import DatabaseBackup
from app.models.mixins import utcnow


@pytest.fixture
def clean_slate(app):
    DatabaseBackup.query.delete()
    db.session.commit()
    yield


def _add(status, hours_ago=0, size=1024):
    backup = DatabaseBackup(
        filename=f'b_{status}_{hours_ago}.dump',
        file_path=f'/nonexistent/b_{status}_{hours_ago}.dump',
        file_size_bytes=size,
        backup_type=DatabaseBackup.TYPE_FULL,
        status=status,
        created_at=utcnow() - timedelta(hours=hours_ago),
    )
    db.session.add(backup)
    db.session.commit()
    return backup


class TestStatistics:

    def test_in_progress_is_not_counted_as_failed(self, clean_slate):
        """`failed` рахували різницею total - completed.

        Копія, яка саме зараз робиться, через це показувалась як невдала --
        тобто сторінка лякала адміна кожного разу під час дампу.
        """
        _add(DatabaseBackup.STATUS_COMPLETED)
        _add(DatabaseBackup.STATUS_FAILED)
        _add(DatabaseBackup.STATUS_IN_PROGRESS)

        stats = DatabaseBackup.get_statistics()

        assert stats['completed'] == 1
        assert stats['failed'] == 1
        assert stats['in_progress'] == 1
        assert stats['total'] == 3

    def test_corrupted_counts_as_failed(self, clean_slate):
        """Пошкоджена копія -- теж не та, на яку можна покластися."""
        _add(DatabaseBackup.STATUS_CORRUPTED)

        assert DatabaseBackup.get_statistics()['failed'] == 1

    def test_total_size_counts_only_usable_copies(self, clean_slate):
        _add(DatabaseBackup.STATUS_COMPLETED, size=1000)
        _add(DatabaseBackup.STATUS_FAILED, size=9999)

        assert DatabaseBackup.get_statistics()['total_size_bytes'] == 1000

    def test_age_of_last_backup_is_reported(self, clean_slate):
        _add(DatabaseBackup.STATUS_COMPLETED, hours_ago=5)

        age = DatabaseBackup.get_statistics()['last_backup_age_hours']

        assert 4.5 < age < 5.5

    def test_age_is_none_without_any_copy(self, clean_slate):
        stats = DatabaseBackup.get_statistics()

        assert stats['last_backup'] is None
        assert stats['last_backup_age_hours'] is None

    def test_failed_copy_does_not_count_as_the_last_one(self, clean_slate):
        """Вік мусить міряти остання ПРИДАТНА копія, а не остання спроба."""
        _add(DatabaseBackup.STATUS_COMPLETED, hours_ago=10)
        _add(DatabaseBackup.STATUS_FAILED, hours_ago=1)

        age = DatabaseBackup.get_statistics()['last_backup_age_hours']

        assert 9.5 < age < 10.5


def test_file_size_display_leaves_attribute_intact():
    """Показ розміру НЕ має псувати сам атрибут.

    Властивість ділила `self.file_size_bytes` у циклі, тобто кожен рендер
    списку перетворював 5 МБ на число 5. Інстанс після цього «брудний», і
    найближчий commit у тому ж запиті записував у базу 5 замість 5242880.
    """
    backup = DatabaseBackup(file_size_bytes=5 * 1024 * 1024)

    assert backup.file_size_display == '5.0 MB'
    assert backup.file_size_bytes == 5 * 1024 * 1024
