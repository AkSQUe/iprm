"""Межі текстових колонок: зовнішній рядок не має класти операцію.

Реальна аварія 12.09.2026, перша справжня копія на проді: `pg_dump --version`
на Ubuntu 24.04 віддає

    pg_dump (PostgreSQL) 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

-- 58 символів у колонку String(50). INSERT упав, CLI вийшов з кодом 1 і
зупинив деплой. Дефект лежав у коді з 12.06.2026 і не стріляв лише тому, що
жодної копії на тому сервері ніколи не робилось.

Межі беруться з моделі, а не числами в тестах: інакше вони розійдуться з
колонками, і тест почне брехати.
"""
import pytest

from app.extensions import db
from app.models.database_backup import DatabaseBackup
from app.services.backup_service import BackupService

PG_URL = 'postgresql://user:pass@localhost:5432/testdb'

UBUNTU_BANNER = 'pg_dump (PostgreSQL) 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)'


def _limit(column_name):
    return DatabaseBackup.__table__.c[column_name].type.length


class _Completed:
    def __init__(self, stdout='', returncode=0):
        self.stdout = stdout
        self.stderr = ''
        self.returncode = returncode


class TestPgDumpVersion:

    def test_ubuntu_banner_fits_the_column(self, app, monkeypatch):
        """Рядок, на якому впав прод."""
        monkeypatch.setattr('subprocess.run',
                            lambda *a, **kw: _Completed(UBUNTU_BANNER))

        value = BackupService._get_pg_dump_version()

        assert value is not None
        assert len(value) <= _limit('pg_dump_version')

    def test_version_number_is_what_gets_stored(self, app, monkeypatch):
        """Номер версії -- те єдине, що справді потрібне.

        Саме його звіряють із версією сервера БД, коли вирішують, чи цією
        копією взагалі можна скористатись. Назва дистрибутива й номер збірки
        -- шум, через який рядок і не влазив.
        """
        monkeypatch.setattr('subprocess.run',
                            lambda *a, **kw: _Completed(UBUNTU_BANNER))

        assert BackupService._get_pg_dump_version() == '16.15'

    def test_plain_banner_without_distro_suffix(self, app, monkeypatch):
        monkeypatch.setattr('subprocess.run',
                            lambda *a, **kw: _Completed('pg_dump (PostgreSQL) 17.2'))

        assert BackupService._get_pg_dump_version() == '17.2'

    def test_unparseable_output_is_still_clamped(self, app, monkeypatch):
        """Навіть на несподіваному виводі колонка не має переповнитись."""
        monkeypatch.setattr('subprocess.run',
                            lambda *a, **kw: _Completed('щось геть інше ' * 20))

        value = BackupService._get_pg_dump_version()

        assert len(value) <= _limit('pg_dump_version')

    def test_empty_output_gives_nothing(self, app, monkeypatch):
        monkeypatch.setattr('subprocess.run', lambda *a, **kw: _Completed(''))

        assert BackupService._get_pg_dump_version() is None

    def test_missing_binary_gives_nothing(self, app, monkeypatch):
        def _boom(*args, **kwargs):
            raise FileNotFoundError('pg_dump')

        monkeypatch.setattr('subprocess.run', _boom)

        assert BackupService._get_pg_dump_version() is None


class TestDescriptionLimit:
    """Той самий клас дефекту поряд: опис приходить ззовні й не обмежений."""

    @pytest.fixture(autouse=True)
    def clean_slate(self, app):
        DatabaseBackup.query.delete()
        db.session.commit()
        yield

    @pytest.fixture
    def working_pg_dump(self, app, monkeypatch):
        monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', PG_URL)
        monkeypatch.setattr('shutil.which', lambda name: f'/usr/bin/{name}')
        monkeypatch.setattr('subprocess.run',
                            lambda *a, **kw: _Completed(UBUNTU_BANNER))
        monkeypatch.setattr('os.path.getsize', lambda path: 2048)
        monkeypatch.setattr(
            BackupService, '_compute_checksum',
            classmethod(lambda cls, path: 'a' * 64),
        )

    def test_overlong_description_does_not_break_the_backup(self, working_pg_dump):
        """У формі адмінки maxlength не було, в CLI -- теж.

        Опис на 1000 символів валив би INSERT так само, як версія pg_dump, і
        так само ховав би це за стектрейсом.
        """
        backup = BackupService.create_backup(description='д' * 1000)

        assert len(backup.description) <= _limit('description')

    def test_normal_description_is_kept_as_is(self, working_pg_dump):
        backup = BackupService.create_backup(description='Перед деплоєм c8c8d78')

        assert backup.description == 'Перед деплоєм c8c8d78'
