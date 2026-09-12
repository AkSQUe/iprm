"""BackupService: передумови середовища й політика очищення.

Справжній pg_dump тут не запускається -- тести перевіряють рішення сервісу,
а не роботу PostgreSQL.
"""
import pytest

from app.extensions import db
from app.models.database_backup import DatabaseBackup
from app.services.backup_service import BackupService, BackupError

PG_URL = 'postgresql://user:pass@localhost:5432/testdb'


@pytest.fixture
def pg_url(app, monkeypatch):
    """Сервіс відмовляється працювати з SQLite, тож підсовуємо URL PostgreSQL.

    Двигун SQLAlchemy вже створений при init_app і цього не читає -- зміна
    видна лише BackupService.
    """
    monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', PG_URL)
    return PG_URL


def test_missing_pg_dump_is_reported_readably(pg_url, monkeypatch):
    """Без postgresql-client сервіс мусить сказати це людською мовою.

    Саме цього бракувало: на проді пакета не було, і джоба падала сирим
    FileNotFoundError у стектрейсі, а не зрозумілим повідомленням.
    """
    monkeypatch.setattr('shutil.which', lambda name: None)

    with pytest.raises(BackupError) as exc:
        BackupService.create_backup()

    assert 'pg_dump' in str(exc.value)


def test_missing_pg_dump_leaves_no_half_written_row(pg_url, monkeypatch):
    """Відмова через середовище не має лишати рядків у стані in_progress.

    Інакше перша ж невдача займає єдиний слот BACKUP_MAX_CONCURRENT і
    блокує всі наступні спроби.
    """
    monkeypatch.setattr('shutil.which', lambda name: None)
    before = DatabaseBackup.query.count()

    with pytest.raises(BackupError):
        BackupService.create_backup()

    assert DatabaseBackup.query.count() == before


def test_schema_only_copy_is_refused_for_restore(pg_url, monkeypatch):
    """Копія «тільки схема» непридатна для відновлення.

    pg_restore --clean знесе всі таблиці й відтворить їх ПОРОЖНІМИ -- тобто
    спроба відновитись із такої копії видаляє дані замість повернути їх.
    Модель це знає (`is_restorable`), але сервіс не питав.
    """
    monkeypatch.setattr('shutil.which', lambda name: f'/usr/bin/{name}')
    backup = DatabaseBackup(
        filename='backup_schema_only_20260912_030000.dump',
        file_path='/nonexistent/backup_schema_only_20260912_030000.dump',
        backup_type=DatabaseBackup.TYPE_SCHEMA_ONLY,
        status=DatabaseBackup.STATUS_COMPLETED,
        checksum_sha256='b' * 64,
    )
    db.session.add(backup)
    db.session.commit()

    with pytest.raises(BackupError) as exc:
        BackupService.restore_backup(backup.id)

    assert 'схем' in str(exc.value).lower()


class TestFilenamesAreUnique:
    """Два дампи не мають ділити один файл."""

    def test_same_second_gives_different_names(self, app):
        """Мітка часу була з точністю до секунди.

        Ручна копія і щоденна джоба, що зійшлись в одну секунду, давали
        однакове ім'я: другий pg_dump перезаписував файл першого, а два
        рядки в базі вказували на нього разом. Видалення одного забирало
        файл у другого.
        """
        first = BackupService._build_filename(DatabaseBackup.TYPE_FULL)
        second = BackupService._build_filename(DatabaseBackup.TYPE_FULL)

        assert first != second

    def test_name_still_carries_type_and_date(self, app):
        name = BackupService._build_filename(DatabaseBackup.TYPE_SCHEMA_ONLY)

        assert name.startswith('backup_schema_only_')
        assert name.endswith('.dump')


class TestDatabaseSizeWithoutSubprocess:
    """Розмір бази беремо з'єднанням, яке вже відкрите."""

    def test_no_psql_process_is_spawned(self, app, monkeypatch):
        """Доти розмір діставали через subprocess psql -- із SQL, зібраним
        f-рядком, і з незадекларованою залежністю: psql немає в
        PG_REQUIRED_BINARIES, тож на сервері без нього db_size_bytes тихо
        лишався NULL.
        """
        def _forbidden(*args, **kwargs):
            raise AssertionError('subprocess тут більше не потрібен')

        monkeypatch.setattr('subprocess.run', _forbidden)

        assert BackupService._get_db_size() is None, 'на SQLite розміру немає'


class TestValidateDistinguishesMissingReference:

    def test_unrecorded_size_is_not_a_mismatch(self, app, tmp_path):
        """Незаписаний розмір означає «еталона немає», а не «не збігається».

        Колонка має default=0, тож незаповнений розмір приходить нулем, а не
        None -- і пряме порівняння `actual != expected` маркувало цілу копію
        як пошкоджену. Еталон цілісності тут checksum, і він збігається.
        """
        import hashlib
        path = tmp_path / 'nosize.dump'
        path.write_bytes(b'payload')
        backup = DatabaseBackup(
            filename=path.name,
            file_path=str(path),
            file_size_bytes=0,
            backup_type=DatabaseBackup.TYPE_FULL,
            status=DatabaseBackup.STATUS_COMPLETED,
            checksum_sha256=hashlib.sha256(b'payload').hexdigest(),
        )
        db.session.add(backup)
        db.session.commit()

        assert BackupService.validate_backup(backup.id) is True
        assert backup.status == DatabaseBackup.STATUS_COMPLETED

    def test_real_size_mismatch_is_still_caught(self, app, tmp_path):
        """Запобіжник не має ослабнути: записаний розмір досі порівнюється."""
        import hashlib
        path = tmp_path / 'short.dump'
        path.write_bytes(b'payload')
        backup = DatabaseBackup(
            filename=path.name,
            file_path=str(path),
            file_size_bytes=99999,
            backup_type=DatabaseBackup.TYPE_FULL,
            status=DatabaseBackup.STATUS_COMPLETED,
            checksum_sha256=hashlib.sha256(b'payload').hexdigest(),
        )
        db.session.add(backup)
        db.session.commit()

        assert BackupService.validate_backup(backup.id) is False
        assert backup.status == DatabaseBackup.STATUS_CORRUPTED


def test_pg_tools_available_follows_binaries(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: None)
    assert BackupService.pg_tools_available() is False

    monkeypatch.setattr('shutil.which', lambda name: f'/usr/bin/{name}')
    assert BackupService.pg_tools_available() is True


def test_pg_tools_available_needs_every_binary(monkeypatch):
    """pg_dump без pg_restore -- це теж непридатне середовище."""
    monkeypatch.setattr(
        'shutil.which', lambda name: '/usr/bin/pg_dump' if name == 'pg_dump' else None,
    )
    assert BackupService.pg_tools_available() is False
