"""Сторінка резервних копій: склад дій і попередження про середовище."""
import pytest

from app.extensions import db
from app.models.database_backup import DatabaseBackup
from app.services.backup_service import BackupService
from tests.support.rbac import make_super_admin

PG_URL = 'postgresql://user:pass@localhost:5432/testdb'


@pytest.fixture
def admin_client(client):
    user = make_super_admin()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    return client


@pytest.fixture
def tools_present(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: f'/usr/bin/{name}')


@pytest.fixture
def tools_missing(monkeypatch):
    monkeypatch.setattr('shutil.which', lambda name: None)


@pytest.fixture
def completed_backup():
    """Готова копія в списку -- інакше тіло циклу в шаблоні не рендериться
    і перевірка кнопок нічого не перевіряє."""
    backup = DatabaseBackup(
        filename='backup_full_20260912_030000.dump',
        file_path='/var/www/iprm/backups/backup_full_20260912_030000.dump',
        file_size_bytes=5 * 1024 * 1024,
        backup_type=DatabaseBackup.TYPE_FULL,
        status=DatabaseBackup.STATUS_COMPLETED,
        checksum_sha256='a' * 64,
    )
    db.session.add(backup)
    db.session.commit()
    return backup


def test_restore_has_no_web_route(app):
    """Відновлення живе лише в CLI.

    pg_restore --clean проти робочої БД, поки gunicorn тримає з'єднання,
    або падає на блокуваннях, або зносить таблиці посеред роботи сайту.
    Кнопці в адмінці там не місце -- лишається `flask backup restore`.
    """
    assert 'admin.backup_restore' not in app.view_functions

    restore_rules = [
        str(rule) for rule in app.url_map.iter_rules()
        if str(rule).startswith('/admin/backups') and 'restore' in str(rule)
    ]
    assert restore_rules == []


def test_listed_backup_offers_no_restore(admin_client, tools_present, completed_backup):
    html = admin_client.get('/admin/backups').get_data(as_text=True)

    assert f'#{completed_backup.id}' in html, 'копія мусить бути в списку'
    assert 'Відновити' not in html


def test_listed_backup_still_offers_download_and_check(
    admin_client, tools_present, completed_backup,
):
    """Прибрати треба рівно відновлення, а не всі дії з копією."""
    html = admin_client.get('/admin/backups').get_data(as_text=True)

    assert f'/admin/backups/{completed_backup.id}/download' in html
    assert f'/admin/backups/{completed_backup.id}/validate' in html


def test_page_warns_when_postgres_tools_are_missing(admin_client, tools_missing):
    """Саме ця діра три місяці лишалась невидимою.

    На сервері не було postgresql-client, сторінка ж виглядала цілком
    здоровою -- жодного слова про те, що створити копію неможливо.
    """
    html = admin_client.get('/admin/backups').get_data(as_text=True)

    assert 'postgresql-client' in html


def test_page_stays_quiet_when_tools_are_present(admin_client, tools_present):
    html = admin_client.get('/admin/backups').get_data(as_text=True)

    assert 'postgresql-client' not in html


def test_create_is_refused_without_postgres_tools(
    app, admin_client, tools_missing, monkeypatch,
):
    monkeypatch.setitem(app.config, 'SQLALCHEMY_DATABASE_URI', PG_URL)

    response = admin_client.post(
        '/admin/backups/create', data={'backup_type': 'full'}, follow_redirects=True,
    )

    assert response.status_code == 200
    assert 'postgresql-client' in response.get_data(as_text=True)
    assert BackupService.pg_tools_available() is False
