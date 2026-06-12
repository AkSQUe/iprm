"""Database backup service using pg_dump / pg_restore.

Provides create, restore, validate, cleanup, and storage statistics.
Uses PostgreSQL advisory locks for multi-worker safety (same pattern
as scheduler_service).
"""
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
    def _get_db_size(conn_info, env):
        try:
            result = subprocess.run(
                ['psql', '-t', '-A', '-c',
                 f"SELECT pg_database_size('{conn_info['dbname']}');"],
                env=env, capture_output=True, text=True, timeout=30,
            )
            return int(result.stdout.strip())
        except Exception:
            return None

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
            raise BackupError('Backup is only supported for PostgreSQL databases')

        in_progress = DatabaseBackup.query.filter_by(
            status=DatabaseBackup.STATUS_IN_PROGRESS,
        ).count()
        max_concurrent = current_app.config.get('BACKUP_MAX_CONCURRENT', 1)
        if in_progress >= max_concurrent:
            raise BackupConcurrencyError(
                f'Maximum concurrent backups ({max_concurrent}) reached',
            )

        storage_path = cls._get_storage_path()
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename = f'backup_{backup_type}_{timestamp}.dump'
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
                raise BackupError(f'pg_dump failed: {result.stderr}')

            duration = time.monotonic() - start_time
            file_size = os.path.getsize(filepath)
            checksum = cls._compute_checksum(filepath)
            db_size = cls._get_db_size(conn_info, env)

            backup.file_size_bytes = file_size
            backup.checksum_sha256 = checksum
            backup.db_size_bytes = db_size
            backup.duration_seconds = round(duration, 2)
            backup.status = DatabaseBackup.STATUS_COMPLETED
            db.session.commit()

            logger.info(
                'Backup created: %s (%s, %s, %.1fs)',
                filename, backup_type, backup.file_size_display, duration,
            )
            return backup

        except subprocess.TimeoutExpired:
            backup.status = DatabaseBackup.STATUS_FAILED
            backup.error_message = 'Backup timed out'
            backup.duration_seconds = time.monotonic() - start_time
            db.session.commit()
            if os.path.exists(filepath):
                os.remove(filepath)
            raise BackupTimeoutError('Backup operation timed out')

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
            raise BackupError(f'Backup {backup_id} not found')
        if backup.status != DatabaseBackup.STATUS_COMPLETED:
            raise BackupError(f'Backup is not in completed status')
        if not os.path.exists(backup.file_path):
            raise BackupError(f'Backup file not found: {backup.file_path}')

        conn_info = cls._parse_db_url(cls._get_db_url())
        if conn_info is None:
            raise BackupError('Restore is only supported for PostgreSQL databases')

        checksum = cls._compute_checksum(backup.file_path)
        if checksum != backup.checksum_sha256:
            backup.status = DatabaseBackup.STATUS_CORRUPTED
            db.session.commit()
            raise BackupValidationError('Checksum mismatch -- backup file is corrupted')

        pre_restore_backup = None
        if not force:
            try:
                pre_restore_backup = cls.create_backup(
                    backup_type=DatabaseBackup.TYPE_PRE_RESTORE,
                    description=f'Auto pre-restore before restoring backup #{backup.id}',
                    created_by_id=created_by_id,
                )
            except Exception:
                logger.exception('Failed to create pre-restore backup')

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

            if result.returncode != 0 and 'WARNING' not in result.stderr:
                raise BackupError(f'pg_restore failed: {result.stderr}')

            logger.info('Backup restored: %s -> %s', backup.filename, conn_info['dbname'])
            return True

        except subprocess.TimeoutExpired:
            raise BackupTimeoutError('Restore operation timed out')

        except Exception as exc:
            if pre_restore_backup and not force:
                logger.warning('Restore failed, attempting rollback from pre-restore backup')
                try:
                    cls.restore_backup(pre_restore_backup.id, force=True)
                    logger.info('Rollback successful')
                except Exception:
                    logger.exception('CRITICAL: Rollback failed!')
                    raise BackupError(
                        f'Restore failed and rollback also failed: {exc}'
                    ) from exc
            raise

    @classmethod
    def validate_backup(cls, backup_id):
        from app.models.database_backup import DatabaseBackup

        backup = DatabaseBackup.query.get(backup_id)
        if not backup:
            raise BackupError(f'Backup {backup_id} not found')
        if not os.path.exists(backup.file_path):
            backup.status = DatabaseBackup.STATUS_FAILED
            backup.error_message = 'Backup file missing from disk'
            from app.extensions import db
            db.session.commit()
            return False

        file_size = os.path.getsize(backup.file_path)
        if file_size != backup.file_size_bytes:
            backup.status = DatabaseBackup.STATUS_CORRUPTED
            backup.error_message = f'File size mismatch: expected {backup.file_size_bytes}, got {file_size}'
            from app.extensions import db
            db.session.commit()
            return False

        checksum = cls._compute_checksum(backup.file_path)
        if checksum != backup.checksum_sha256:
            backup.status = DatabaseBackup.STATUS_CORRUPTED
            backup.error_message = 'Checksum mismatch'
            from app.extensions import db
            db.session.commit()
            return False

        return True

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
        logger.info('Backup deleted: %s', backup.filename)

    @classmethod
    def cleanup_old_backups(cls, dry_run=False):
        from app.extensions import db
        from app.models.database_backup import DatabaseBackup

        retention_days = current_app.config.get('BACKUP_RETENTION_DAYS', 30)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        old_backups = (
            DatabaseBackup.query
            .filter(
                DatabaseBackup.created_at < cutoff,
                DatabaseBackup.status == DatabaseBackup.STATUS_COMPLETED,
                DatabaseBackup.backup_type != DatabaseBackup.TYPE_PRE_RESTORE,
            )
            .order_by(DatabaseBackup.created_at.asc())
            .all()
        )

        pre_restore_cutoff = datetime.now(timezone.utc) - timedelta(days=1)
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
                'backups': [{'id': b.id, 'filename': b.filename, 'date': str(b.created_at)} for b in to_delete],
            }

        deleted = 0
        for backup in to_delete:
            try:
                if os.path.exists(backup.file_path):
                    os.remove(backup.file_path)
                db.session.delete(backup)
                deleted += 1
            except Exception:
                logger.exception('Failed to delete backup %s', backup.id)

        db.session.commit()
        logger.info('Cleanup: deleted %d old backups', deleted)
        return {'deleted': deleted}

    @classmethod
    def get_storage_stats(cls):
        from app.models.database_backup import DatabaseBackup

        storage_path = cls._get_storage_path()
        total, used, free = shutil.disk_usage(storage_path)

        stats = DatabaseBackup.get_statistics()
        stats['disk_total'] = total
        stats['disk_used'] = used
        stats['disk_free'] = free
        stats['storage_path'] = storage_path

        return stats
