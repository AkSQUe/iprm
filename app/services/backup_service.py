"""Резервне копіювання БД через pg_dump / pg_restore.

Створення, відновлення, перевірка цілісності, очищення за retention і
статистика сховища.

Про одночасність, бо докстрінг тут раніше обіцяв неправду. Advisory-локів
у цьому сервісі НЕМА -- ними захищені джоби планувальника
(`scheduler_service._job_lock`), тобто той шлях, де воркери справді б'ються
за один запуск. Веб-шлях стримує лічильник BACKUP_MAX_CONCURRENT, і він
неатомарний: два одночасні запити теоретично пройдуть разом. Це прийнятно
(дві копії -- не втрата даних, а зайвий файл), а головну небезпеку --
рядок, що застряг у in_progress назавжди, -- знімає reap_stuck_backups.
"""
import hashlib
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from flask import current_app

logger = logging.getLogger(__name__)


class BackupError(Exception):
    pass


class BackupTimeoutError(BackupError):
    pass


class BackupConcurrencyError(BackupError):
    pass


class BackupValidationError(BackupError):
    pass


class BackupService:

    # Без цих утиліт бекапи неможливі в принципі. Копія, яку нічим не
    # відновити, бекапом не є, тому pg_restore вимагається разом з pg_dump.
    PG_REQUIRED_BINARIES = ('pg_dump', 'pg_restore')

    @classmethod
    def missing_pg_tools(cls):
        """Перелік утиліт PostgreSQL, яких немає в PATH."""
        return [name for name in cls.PG_REQUIRED_BINARIES if not shutil.which(name)]

    @classmethod
    def pg_tools_available(cls):
        return not cls.missing_pg_tools()

    @staticmethod
    def _get_storage_path():
        path = current_app.config.get(
            'BACKUP_STORAGE_PATH',
            os.path.join(os.path.dirname(current_app.root_path), 'backups'),
        )
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _get_db_url():
        return current_app.config['SQLALCHEMY_DATABASE_URI']

    @staticmethod
    def _parse_db_url(url):
        if url.startswith('postgresql+pg8000://'):
            url = url.replace('postgresql+pg8000://', 'postgresql://')
        if url.startswith('sqlite://'):
            return None
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return {
            'host': parsed.hostname or 'localhost',
            'port': parsed.port or 5432,
            'user': parsed.username or 'postgres',
            'password': parsed.password or '',
            'dbname': parsed.path.lstrip('/'),
        }

    @staticmethod
    def _get_env(conn_info):
        env = os.environ.copy()
        env['PGHOST'] = conn_info['host']
        env['PGPORT'] = str(conn_info['port'])
        env['PGUSER'] = conn_info['user']
        env['PGDATABASE'] = conn_info['dbname']
        if conn_info['password']:
            env['PGPASSWORD'] = conn_info['password']
        return env

    @staticmethod
    def _compute_checksum(filepath):
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def _get_db_size():
        """Розмір бази -- з'єднанням, яке вже відкрите.

        Доти це робив subprocess `psql` із SQL, зібраним f-рядком. Три
        наслідки: незадекларована залежність (psql немає в
        PG_REQUIRED_BINARIES, тож без нього метрика тихо лишалась NULL),
        зайвий процес і інтерполяція в запит.

        Окреме з'єднання, а не db.session: невдалий запит на PostgreSQL
        обриває транзакцію, і тоді найближчий commit у create_backup не
        зміг би позначити копію завершеною.
        """
        from sqlalchemy import text

        from app.extensions import db

        # Функція суто постгресова: на іншому діалекті навіть не пробуємо.
        if db.engine.dialect.name != 'postgresql':
            return None

        try:
            # SAVEPOINT, а не окреме з'єднання: невдалий запит обриває
            # транзакцію, і тоді найближчий commit у create_backup не зміг
            # би позначити копію завершеною. Окреме ж з'єднання з двигуна
            # конфліктує з уже відкритою транзакцією.
            with db.session.begin_nested():
                size = db.session.execute(
                    text('SELECT pg_database_size(current_database())'),
                ).scalar()
            return int(size) if size is not None else None
        except Exception:
            # Немає прав чи інша відмова. Це метрика для показу, не причина
            # валити копію.
            return None

    @staticmethod
    def _build_filename(backup_type):
        """Ім'я файлу копії: тип, час і короткий унікальний хвіст.

        Секундної точності недосить: ручна копія і щоденна джоба можуть
        зійтись в одну секунду, і тоді другий дамп перезаписав би файл
        першого, а два рядки в базі вказували б на нього разом -- видалення
        одного забирало б файл у другого.
        """
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        return f'backup_{backup_type}_{timestamp}_{uuid4().hex[:6]}.dump'

    @staticmethod
    def _get_pg_dump_version():
        try:
            result = subprocess.run(
                ['pg_dump', '--version'], capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip().split('\n')[0]
        except Exception:
            return None

    @classmethod
    def create_backup(cls, backup_type='full', description='', created_by_id=None):
        from app.extensions import db
        from app.models.database_backup import DatabaseBackup

        conn_info = cls._parse_db_url(cls._get_db_url())
        if conn_info is None:
            raise BackupError('Резервне копіювання працює лише з PostgreSQL')

        # Перевірка середовища ДО створення рядка: інакше перша ж невдача
        # займає єдиний слот BACKUP_MAX_CONCURRENT назавжди.
        missing = cls.missing_pg_tools()
        if missing:
            raise BackupError(
                'Не знайдено утиліт PostgreSQL: ' + ', '.join(missing)
                + '. Встановіть на сервері пакет postgresql-client.',
            )

        # Спершу прибрати мертві операції, інакше один рядок, що застряг
        # після перезапуску воркера, блокує створення копій назавжди.
        cls.reap_stuck_backups()

        in_progress = DatabaseBackup.query.filter_by(
            status=DatabaseBackup.STATUS_IN_PROGRESS,
        ).count()
        max_concurrent = current_app.config.get('BACKUP_MAX_CONCURRENT', 1)
        if in_progress >= max_concurrent:
            raise BackupConcurrencyError(
                'Уже виконується інша операція резервного копіювання '
                f'(ліміт: {max_concurrent}). Спробуйте трохи пізніше.',
            )

        storage_path = cls._get_storage_path()
        filename = cls._build_filename(backup_type)
        filepath = os.path.join(storage_path, filename)

        backup = DatabaseBackup(
            filename=filename,
            file_path=filepath,
            backup_type=backup_type,
            status=DatabaseBackup.STATUS_IN_PROGRESS,
            compression='gzip',
            description=description,
            pg_dump_version=cls._get_pg_dump_version(),
            created_by_id=created_by_id,
        )
        db.session.add(backup)
        db.session.commit()

        start_time = time.monotonic()
        try:
            env = cls._get_env(conn_info)

            cmd = ['pg_dump', '--format=custom', '--compress=5']
            if backup_type == DatabaseBackup.TYPE_SCHEMA_ONLY:
                cmd.append('--schema-only')
            elif backup_type == DatabaseBackup.TYPE_DATA_ONLY:
                cmd.append('--data-only')
            cmd.extend(['--file', filepath, conn_info['dbname']])

            timeout = current_app.config.get('BACKUP_OPERATION_TIMEOUT', 3600)
            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=timeout,
            )

            if result.returncode != 0:
                raise BackupError(
                    'pg_dump завершився з кодом '
                    f'{result.returncode}: {cls._tail(result.stderr)}',
                )

            duration = time.monotonic() - start_time
            file_size = os.path.getsize(filepath)
            checksum = cls._compute_checksum(filepath)
            db_size = cls._get_db_size()

            backup.file_size_bytes = file_size
            backup.checksum_sha256 = checksum
            backup.db_size_bytes = db_size
            backup.duration_seconds = round(duration, 2)
            backup.status = DatabaseBackup.STATUS_COMPLETED
            db.session.commit()

            logger.info(
                'Копію створено: %s (%s, %s, %.1f с)',
                filename, backup_type, backup.file_size_display, duration,
            )
            return backup

        except subprocess.TimeoutExpired:
            backup.status = DatabaseBackup.STATUS_FAILED
            backup.error_message = 'Створення копії перевищило відведений час'
            backup.duration_seconds = time.monotonic() - start_time
            db.session.commit()
            if os.path.exists(filepath):
                os.remove(filepath)
            raise BackupTimeoutError(
                'Створення копії перевищило відведений час',
            )

        except Exception as exc:
            backup.status = DatabaseBackup.STATUS_FAILED
            backup.error_message = str(exc)[:2000]
            backup.duration_seconds = time.monotonic() - start_time
            db.session.commit()
            if os.path.exists(filepath):
                os.remove(filepath)
            raise

    @classmethod
    def restore_backup(cls, backup_id, force=False, created_by_id=None):
        from app.extensions import db
        from app.models.database_backup import DatabaseBackup

        backup = DatabaseBackup.query.get(backup_id)
        if not backup:
            raise BackupError(f'Копію #{backup_id} не знайдено')
        if backup.status != DatabaseBackup.STATUS_COMPLETED:
            raise BackupError('Копія не має статусу «завершено»')
        if backup.backup_type == DatabaseBackup.TYPE_SCHEMA_ONLY:
            # --clean знесе таблиці й відтворить їх порожніми: така спроба
            # відновлення видаляє дані, а не повертає їх.
            raise BackupError(
                'Копія містить лише схему без даних -- відновлення з неї '
                'знищило б наявні дані. Скористайтесь повною копією.',
            )
        if not os.path.exists(backup.file_path):
            raise BackupError(f'Файл копії не знайдено: {backup.file_path}')

        conn_info = cls._parse_db_url(cls._get_db_url())
        if conn_info is None:
            raise BackupError('Відновлення працює лише з PostgreSQL')

        checksum = cls._compute_checksum(backup.file_path)
        if checksum != backup.checksum_sha256:
            backup.status = DatabaseBackup.STATUS_CORRUPTED
            db.session.commit()
            raise BackupValidationError(
                'Контрольна сума не збігається -- файл копії пошкоджено'
            )

        pre_restore_backup = None
        if not force:
            try:
                pre_restore_backup = cls.create_backup(
                    backup_type=DatabaseBackup.TYPE_PRE_RESTORE,
                    description=f'Запобіжна копія перед відновленням #{backup.id}',
                    created_by_id=created_by_id,
                )
            except Exception as exc:
                # Відновлення без шляху назад не починаємо. Доти збій
                # страхувальної копії лише писався в лог, а найнебезпечніша
                # операція в системі йшла далі -- і людина про це не знала.
                logger.exception('Не вдалось створити запобіжну копію')
                raise BackupError(
                    'Запобіжну копію перед відновленням створити не вдалось '
                    f'({exc}). Відновлення скасовано: повертатись було б '
                    'нізвідки. Свідома відмова від страхування -- прапорець '
                    '--force.',
                ) from exc

        try:
            env = cls._get_env(conn_info)
            timeout = current_app.config.get('BACKUP_OPERATION_TIMEOUT', 3600)

            cmd = [
                'pg_restore', '--clean', '--if-exists',
                '--no-owner', '--no-privileges',
                '--dbname', conn_info['dbname'],
                backup.file_path,
            ]

            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=timeout,
            )

            # Рішення ЛИШЕ за кодом виходу. Доти умова була
            # `returncode != 0 and 'WARNING' not in stderr`, а pg_restore
            # друкує попередження майже завжди -- тож справжній провал
            # проходив як успіх, і в журнал ішло "Backup restored" на
            # зруйнованій базі.
            if result.returncode != 0:
                raise BackupError(
                    'pg_restore завершився з кодом '
                    f'{result.returncode}: {cls._tail(result.stderr)}',
                )

            logger.info('Базу відновлено з копії %s -> %s',
                        backup.filename, conn_info['dbname'])
            return True

        except subprocess.TimeoutExpired:
            raise BackupTimeoutError('Restore operation timed out')

        except Exception as exc:
            if pre_restore_backup and not force:
                logger.warning('Відновлення впало, відкочуємось на запобіжну копію')
                try:
                    cls.restore_backup(pre_restore_backup.id, force=True)
                    logger.info('Відкат успішний')
                except Exception:
                    logger.exception('КРИТИЧНО: відкат не вдався')
                    raise BackupError(
                        f'Відновлення впало, і відкат теж не вдався: {exc}'
                    ) from exc
            raise

    @classmethod
    def validate_backup(cls, backup_id):
        """Чи лежить на диску той самий файл, що й був знятий.

        Повертає False і позначає копію, якщо ні. Еталон -- checksum;
        розмір лише дешева попередня перевірка.
        """
        from app.extensions import db
        from app.models.database_backup import DatabaseBackup

        backup = DatabaseBackup.query.get(backup_id)
        if not backup:
            raise BackupError(f'Копію #{backup_id} не знайдено')

        def _mark(status, message):
            backup.status = status
            backup.error_message = message
            db.session.commit()
            return False

        if not backup.file_path or not os.path.exists(backup.file_path):
            return _mark(DatabaseBackup.STATUS_FAILED,
                         'Файл копії відсутній на диску')

        expected_size = backup.file_size_bytes
        actual_size = os.path.getsize(backup.file_path)
        # Порожній еталон означає «розміру не записано», а не «не збігається».
        # Колонка має default=0, тож незаповнений розмір приходить нулем, а не
        # None -- і пряме порівняння маркувало живу копію як пошкоджену.
        # Справжній еталон цілісності все одно checksum нижче, а нульовий
        # дамп вона й зловить.
        if expected_size and actual_size != expected_size:
            return _mark(
                DatabaseBackup.STATUS_CORRUPTED,
                f'Розмір не збігається: очікували {expected_size}, '
                f'на диску {actual_size}',
            )

        if not backup.checksum_sha256:
            # Без контрольної суми підтвердити цілісність нічим.
            return _mark(DatabaseBackup.STATUS_CORRUPTED,
                         'Контрольної суми копії немає -- перевірити нічим')

        if cls._compute_checksum(backup.file_path) != backup.checksum_sha256:
            return _mark(DatabaseBackup.STATUS_CORRUPTED,
                         'Контрольна сума не збігається')

        return True

    @classmethod
    def validate_all_backups(cls):
        """Перевірити цілісність усіх придатних копій.

        Поштучна перевірка знаходить гниль лише там, куди адмін сам клікнув,
        а копія потрібна рівно один раз -- і саме тоді з'ясовується, що файл
        давно побитий. Тому є і кнопка, і щотижнева джоба.

        Перевіряються лише завершені копії: на failed і corrupted і так
        ніхто не покладається.
        """
        from app.models.database_backup import DatabaseBackup

        ids = [
            row[0] for row in
            DatabaseBackup.query
            .with_entities(DatabaseBackup.id)
            .filter(DatabaseBackup.status == DatabaseBackup.STATUS_COMPLETED)
            .order_by(DatabaseBackup.created_at.desc())
            .all()
        ]

        checked = 0
        corrupted = 0
        for backup_id in ids:
            try:
                if cls.validate_backup(backup_id):
                    checked += 1
                else:
                    corrupted += 1
            except Exception:
                # Збій на одній копії не має зривати перевірку решти.
                logger.exception('Перевірка копії #%s не вдалась', backup_id)

        if corrupted:
            logger.warning(
                'Перевірка копій: %d придатних, %d пошкоджених', checked, corrupted)
        else:
            logger.info('Перевірка копій: усі %d придатні', checked)
        return {'checked': checked, 'corrupted': corrupted}

    @classmethod
    def delete_backup(cls, backup_id):
        from app.extensions import db
        from app.models.database_backup import DatabaseBackup

        backup = DatabaseBackup.query.get(backup_id)
        if not backup:
            raise BackupError(f'Backup {backup_id} not found')

        if os.path.exists(backup.file_path):
            os.remove(backup.file_path)

        db.session.delete(backup)
        db.session.commit()
        logger.info('Копію видалено: %s', backup.filename)

    @classmethod
    def reap_stuck_backups(cls):
        """Перевести в failed рядки, що застрягли в in_progress.

        Процес, який робив копію, може не дожити до кінця: перезапуск
        gunicorn посеред дампу, OOM killer, падіння машини. Рядок тоді
        лишається in_progress НАЗАВЖДИ, а оскільки BACKUP_MAX_CONCURRENT
        дорівнює одиниці, кожна наступна копія відмовляється створюватись.
        Система знову вмирає молча -- саме цього тут і не було.

        Межа -- BACKUP_OPERATION_TIMEOUT: довше за нього жодна жива операція
        не триває, бо її вбиває власний таймаут.
        """
        from app.extensions import db
        from app.models.database_backup import DatabaseBackup

        timeout = current_app.config.get('BACKUP_OPERATION_TIMEOUT', 3600)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout)

        stuck = (
            DatabaseBackup.query
            .filter(
                DatabaseBackup.status == DatabaseBackup.STATUS_IN_PROGRESS,
                DatabaseBackup.created_at < cutoff,
            )
            .all()
        )
        if not stuck:
            return 0

        for backup in stuck:
            backup.status = DatabaseBackup.STATUS_FAILED
            backup.error_message = (
                'Операцію перервано: процес не дожив до завершення '
                f'(минуло понад {timeout} с без результату).'
            )
            # Недописаний дамп відновити нічим, а місце він займає.
            cls._remove_file_quietly(backup.file_path)

        db.session.commit()
        logger.warning('Знято %d застряглих операцій резервного копіювання', len(stuck))
        return len(stuck)

    @staticmethod
    def _tail(text, limit=1200):
        """Хвіст виводу утиліти: причина збою стоїть у кінці, не на початку."""
        text = (text or '').strip()
        if len(text) <= limit:
            return text
        return '...' + text[-limit:]

    @staticmethod
    def _remove_file_quietly(path):
        """Прибрати файл копії, не зводячи збій файлової системи в аварію."""
        if not path or not os.path.exists(path):
            return
        try:
            os.remove(path)
        except OSError:
            logger.exception('Не вдалось видалити файл копії %s', path)

    @classmethod
    def _protected_ids(cls, min_keep):
        """ID найсвіжіших завершених копій, які не видаляються за віком."""
        from app.extensions import db
        from app.models.database_backup import DatabaseBackup

        if min_keep <= 0:
            return set()
        rows = (
            db.session.query(DatabaseBackup.id)
            .filter(
                DatabaseBackup.status == DatabaseBackup.STATUS_COMPLETED,
                DatabaseBackup.backup_type != DatabaseBackup.TYPE_PRE_RESTORE,
            )
            .order_by(DatabaseBackup.created_at.desc())
            .limit(min_keep)
            .all()
        )
        return {row[0] for row in rows}

    @classmethod
    def cleanup_old_backups(cls, dry_run=False):
        from app.extensions import db
        from app.models.database_backup import DatabaseBackup

        if not dry_run:
            cls.reap_stuck_backups()

        retention_days = current_app.config.get('BACKUP_RETENTION_DAYS', 30)
        min_keep = current_app.config.get('BACKUP_MIN_KEEP', 3)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        # Підлога важливіша за вік: краще тримати три давні копії, ніж
        # залишитись без жодної через те, що місяць ніхто не бекапив.
        protected = cls._protected_ids(min_keep)

        old_query = (
            DatabaseBackup.query
            .filter(
                DatabaseBackup.created_at < cutoff,
                DatabaseBackup.status == DatabaseBackup.STATUS_COMPLETED,
                DatabaseBackup.backup_type != DatabaseBackup.TYPE_PRE_RESTORE,
            )
        )
        if protected:
            old_query = old_query.filter(DatabaseBackup.id.notin_(protected))
        old_backups = old_query.order_by(DatabaseBackup.created_at.asc()).all()

        pre_restore_days = current_app.config.get(
            'BACKUP_PRE_RESTORE_RETENTION_DAYS', 1)
        pre_restore_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=pre_restore_days))
        pre_restore_old = (
            DatabaseBackup.query
            .filter(
                DatabaseBackup.created_at < pre_restore_cutoff,
                DatabaseBackup.backup_type == DatabaseBackup.TYPE_PRE_RESTORE,
            )
            .all()
        )

        to_delete = old_backups + pre_restore_old

        if dry_run:
            return {
                'would_delete': len(to_delete),
                'backups': [
                    {'id': b.id, 'filename': b.filename, 'date': str(b.created_at)}
                    for b in to_delete
                ],
            }

        deleted = 0
        for backup in to_delete:
            path = backup.file_path
            try:
                db.session.delete(backup)
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.exception('Не вдалось видалити запис копії %s', backup.id)
                continue
            # Рядок знято першим НАВМИСНО: осиротілий файл лише займає місце,
            # а рядок без файлу validate позначив би як пошкоджену копію, і
            # адмін вважав би, що дамп згнив.
            cls._remove_file_quietly(path)
            deleted += 1

        logger.info('Очищення копій: видалено %d', deleted)
        return {'deleted': deleted}

    @classmethod
    def get_storage_stats(cls):
        """Стан сховища копій для сторінки, разом із двома тривогами.

        Тривоги тут, а не лише в журналі, НАВМИСНО: система вже простояла
        мертвою три місяці саме тому, що ламалась молча, а сторінка при
        цьому виглядала цілком здоровою.
        """
        from app.models.database_backup import DatabaseBackup

        storage_path = cls._get_storage_path()
        total, used, free = shutil.disk_usage(storage_path)

        stats = DatabaseBackup.get_statistics()
        stats['storage_path'] = storage_path
        stats['disk_total'] = total
        stats['disk_used'] = used
        stats['disk_free'] = free
        stats['disk_free_percent'] = int(free / total * 100) if total else 0

        # Єдині одиниці: і тут, і в таблиці -- по 1024. Доти сторінка брала
        # фільтр Jinja filesizeformat, який ділить на 1000.
        stats['total_size_display'] = DatabaseBackup.humanize_size(
            stats['total_size_bytes'])
        stats['disk_free_display'] = DatabaseBackup.humanize_size(free)

        min_percent = current_app.config.get('BACKUP_DISK_FREE_MIN_PERCENT', 10)
        # Повний диск кладе ВЕСЬ сайт, а не лише резервне копіювання.
        stats['disk_low'] = stats['disk_free_percent'] < min_percent

        max_age_hours = current_app.config.get('BACKUP_MAX_AGE_HOURS', 48)
        age = stats['last_backup_age_hours']
        # Нуль копій -- найтривожніший стан, а не нейтральний.
        stats['is_stale'] = age is None or age > max_age_hours
        stats['max_age_hours'] = max_age_hours

        return stats
