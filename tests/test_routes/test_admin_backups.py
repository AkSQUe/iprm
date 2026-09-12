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
def roomy_disk(monkeypatch):
    """Диск із запасом: інакше стан реальної машини прогону керував би тестом."""
    total = 100 * 1024 ** 3
    monkeypatch.setattr('shutil.disk_usage',
                        lambda path: (total, total // 2, total // 2))


@pytest.fixture
def full_disk(monkeypatch):
    total = 100 * 1024 ** 3
    free = int(total * 0.02)
    monkeypatch.setattr('shutil.disk_usage',
                        lambda path: (total, total - free, free))


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


@pytest.fixture
def stale_backup():
    """Копія, старша за BACKUP_MAX_AGE_HOURS."""
    from datetime import timedelta

    from app.models.mixins import utcnow

    backup = DatabaseBackup(
        filename='backup_full_20260801_030000.dump',
        file_path='/var/www/iprm/backups/backup_full_20260801_030000.dump',
        file_size_bytes=5 * 1024 * 1024,
        backup_type=DatabaseBackup.TYPE_FULL,
        status=DatabaseBackup.STATUS_COMPLETED,
        checksum_sha256='b' * 64,
        created_at=utcnow() - timedelta(days=10),
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


class TestPageUsesTheAdminShell:
    """Сторінка мусить жити в тій самій оболонці, що решта адмінки."""

    def test_sidebar_is_present(self, admin_client, tools_present, roomy_disk):
        """Без сайдбара сторінка -- навігаційний тупик.

        Решта 77 сторінок адмінки має сайдбар, а ця будувала власну
        оболонку .admin-page поверх base.html: адмін, перейшовши сюди з
        сайдбара, втрачав його зовсім.
        """
        html = admin_client.get('/admin/backups').get_data(as_text=True)

        assert 'admin-sidebar' in html

    def test_shared_hero_instead_of_a_private_shell(
        self, admin_client, tools_present, roomy_disk,
    ):
        html = admin_client.get('/admin/backups').get_data(as_text=True)

        assert 'admin-hero__title' in html
        assert 'admin-page__header' not in html

    def test_breadcrumb_leads_back_to_dashboard(
        self, admin_client, tools_present, roomy_disk,
    ):
        html = admin_client.get('/admin/backups').get_data(as_text=True)

        assert 'admin-breadcrumb' in html


class TestPageShowsTheAlarms:
    """Стан сховища мусить бути видимим, а не лежати в журналі."""

    def test_missing_copies_are_announced(
        self, admin_client, tools_present, roomy_disk,
    ):
        """Нуль копій -- найтривожніший стан.

        Саме так виглядала сторінка три місяці: порожній список і ані слова
        про те, що копій не створювалось узагалі.
        """
        html = admin_client.get('/admin/backups').get_data(as_text=True)

        assert 'Копій бази немає' in html

    def test_old_copy_is_announced(
        self, admin_client, tools_present, roomy_disk, stale_backup,
    ):
        html = admin_client.get('/admin/backups').get_data(as_text=True)

        assert 'застаріла' in html

    def test_fresh_copy_raises_no_alarm(
        self, admin_client, tools_present, roomy_disk, completed_backup,
    ):
        html = admin_client.get('/admin/backups').get_data(as_text=True)

        assert 'застаріла' not in html
        assert 'Копій бази немає' not in html

    def test_low_disk_space_is_announced(
        self, admin_client, tools_present, full_disk, completed_backup,
    ):
        """Повний диск кладе весь сайт, не лише копіювання."""
        html = admin_client.get('/admin/backups').get_data(as_text=True)

        assert 'Мало місця на диску' in html

    def test_roomy_disk_is_quiet(
        self, admin_client, tools_present, roomy_disk, completed_backup,
    ):
        html = admin_client.get('/admin/backups').get_data(as_text=True)

        assert 'Мало місця на диску' not in html

    def test_sizes_use_one_unit_system(
        self, admin_client, tools_present, roomy_disk, completed_backup,
    ):
        """5 МіБ копії мусять читатись однаково в картці й у рядку таблиці."""
        html = admin_client.get('/admin/backups').get_data(as_text=True)

        assert html.count('5.0 MB') >= 2
        assert '5.2 MB' not in html, 'filesizeformat ділить на 1000'


class TestValidateIsAWriteOperation:
    """Перевірка цілісності МІНЯЄ стан, тож мусить поводитись як запис."""

    def test_validate_is_not_reachable_by_get(self, admin_client, completed_backup):
        """GET не має права міняти дані.

        Маршрут стояв на GET і перемаркьовував копію (completed -> failed):
        CSRF не діє, а префетч посилання браузером міг зіпсувати статус
        без жодної дії людини.
        """
        response = admin_client.get(f'/admin/backups/{completed_backup.id}/validate')

        assert response.status_code == 405

    def test_validate_works_by_post(self, admin_client, completed_backup):
        response = admin_client.post(
            f'/admin/backups/{completed_backup.id}/validate', follow_redirects=True,
        )

        assert response.status_code == 200

    def test_validate_requires_manage_not_view(self, app):
        """Право перегляду не дає права псувати статуси."""
        view = app.view_functions['admin.backup_validate']

        assert view._rbac_permissions == ('backup.manage',)


def test_description_field_has_a_length_limit(
    admin_client, tools_present, roomy_disk,
):
    """Межа стоїть на обох рівнях: браузер і сервіс.

    Колонка -- String(500), і опис приходить ззовні. Поле без maxlength
    означало б, що задовгий опис валить INSERT стектрейсом.
    """
    html = admin_client.get('/admin/backups').get_data(as_text=True)

    assert 'name="description" maxlength="500"' in html


class TestBatchValidation:

    def test_page_offers_checking_every_copy(
        self, admin_client, tools_present, roomy_disk, completed_backup,
    ):
        html = admin_client.get('/admin/backups').get_data(as_text=True)

        assert url_for_validate_all() in html

    def test_batch_validation_runs_by_post(
        self, admin_client, tools_present, completed_backup,
    ):
        response = admin_client.post(
            url_for_validate_all(), follow_redirects=True,
        )

        assert response.status_code == 200
        assert 'переврено' in response.get_data(as_text=True) \
            or 'Перевірено' in response.get_data(as_text=True)

    def test_batch_validation_is_not_a_get(self, admin_client):
        assert admin_client.get(url_for_validate_all()).status_code == 405

    def test_batch_validation_needs_manage(self, app):
        view = app.view_functions['admin.backup_validate_all']

        assert view._rbac_permissions == ('backup.manage',)


def url_for_validate_all():
    return '/admin/backups/validate-all'


class TestMissingIdsGiveNotFound:

    def test_delete_of_unknown_id_is_404(self, admin_client):
        """query.get(...).filename на None давало AttributeError -> 500."""
        response = admin_client.post('/admin/backups/999999/delete')

        assert response.status_code == 404

    def test_validate_of_unknown_id_is_404(self, admin_client):
        response = admin_client.post('/admin/backups/999999/validate')

        assert response.status_code == 404

    def test_download_of_unknown_id_is_404(self, admin_client):
        response = admin_client.get('/admin/backups/999999/download')

        assert response.status_code == 404


def test_stats_endpoint_is_gone(app):
    """JSON-ендпоінт віддавав 500, щойно існувала хоч одна копія.

    jsonify() отримував у stats['last_backup'] інстанс моделі ->
    TypeError: Object of type DatabaseBackup is not JSON serializable.
    Споживача в коді не було жодного, тож маршрут прибрано, а не залатано.
    """
    assert 'admin.backup_stats' not in app.view_functions


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
