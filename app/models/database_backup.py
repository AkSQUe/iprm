"""Модель обліку резервних копій бази даних."""
from datetime import datetime, timezone

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class DatabaseBackup(TimestampMixin, db.Model):
    __tablename__ = 'database_backups'

    TYPE_FULL = 'full'
    TYPE_SCHEMA_ONLY = 'schema_only'
    TYPE_DATA_ONLY = 'data_only'
    TYPE_PRE_RESTORE = 'pre_restore'
    TYPES = (TYPE_FULL, TYPE_SCHEMA_ONLY, TYPE_DATA_ONLY, TYPE_PRE_RESTORE)

    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CORRUPTED = 'corrupted'
    STATUSES = (STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_FAILED, STATUS_CORRUPTED)

    id = db.Column(BigIntPK, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size_bytes = db.Column(db.BigInteger, default=0)
    backup_type = db.Column(db.String(20), nullable=False, default=TYPE_FULL)
    status = db.Column(db.String(20), nullable=False, default=STATUS_IN_PROGRESS)
    compression = db.Column(db.String(10), default='gzip')
    checksum_sha256 = db.Column(db.String(64))
    description = db.Column(db.String(500), default='')
    pg_dump_version = db.Column(db.String(50))
    db_size_bytes = db.Column(db.BigInteger)
    duration_seconds = db.Column(db.Float)
    error_message = db.Column(db.Text)
    created_by_id = db.Column(db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'))

    __table_args__ = (
        db.CheckConstraint(
            "backup_type IN ('full', 'schema_only', 'data_only', 'pre_restore')",
            name='ck_database_backups_type',
        ),
        db.CheckConstraint(
            "status IN ('in_progress', 'completed', 'failed', 'corrupted')",
            name='ck_database_backups_status',
        ),
        db.CheckConstraint('file_size_bytes >= 0', name='ck_database_backups_size_non_negative'),
        # Статистика шукає останню успішну копію, очищення -- завершені
        # старші за retention: обидва запити фільтрують за статусом і
        # сортують за датою.
        db.Index('ix_database_backups_status_created', 'status', 'created_at'),
    )

    created_by = db.relationship('User', foreign_keys=[created_by_id], lazy='joined')

    def __repr__(self):
        return f'<DatabaseBackup {self.id} {self.backup_type} {self.status}>'

    @property
    def is_restorable(self):
        return self.status == self.STATUS_COMPLETED and self.backup_type != self.TYPE_SCHEMA_ONLY

    @staticmethod
    def humanize_size(size_bytes):
        """Байти в людський рядок по 1024.

        Публічна НАВМИСНО: сторінка показує і розмір копії, і вільне місце
        на диску, і доти друга половина рахувалась фільтром Jinja
        `filesizeformat`, який ділить на 1000. Той самий файл виходив двома
        різними числами на одному екрані.
        """
        size = size_bytes
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024:
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{size:.1f} TB'

    @property
    def file_size_display(self):
        if not self.file_size_bytes:
            return '0 B'
        return self.humanize_size(self.file_size_bytes)

    @property
    def db_size_display(self):
        if not self.db_size_bytes:
            return '-'
        return self.humanize_size(self.db_size_bytes)

    @classmethod
    def get_statistics(cls):
        """Агрегати для сторінки: лічильники одним запитом плюс остання копія.

        Було чотири окремі запити. І `failed` рахувався різницею
        `total - completed`, тобто копія, яка саме зараз робиться,
        показувалась як невдала -- сторінка лякала адміна щоразу під час
        дампу.
        """
        from sqlalchemy import case, func

        total, completed, in_progress, total_size = (
            db.session.query(
                func.count(cls.id),
                func.count(case((cls.status == cls.STATUS_COMPLETED, 1))),
                func.count(case((cls.status == cls.STATUS_IN_PROGRESS, 1))),
                func.sum(case(
                    (cls.status == cls.STATUS_COMPLETED, cls.file_size_bytes),
                    else_=0,
                )),
            ).one()
        )

        last_backup = (
            cls.query
            .filter(cls.status == cls.STATUS_COMPLETED)
            .order_by(cls.created_at.desc())
            .first()
        )

        return {
            'total': total or 0,
            'completed': completed or 0,
            'in_progress': in_progress or 0,
            # Усе, що не завершене і не в роботі: failed і corrupted разом --
            # на жодну з них покластися не можна.
            'failed': (total or 0) - (completed or 0) - (in_progress or 0),
            'total_size_bytes': total_size or 0,
            'last_backup': last_backup,
            'last_backup_age_hours': cls._age_in_hours(last_backup),
        }

    @staticmethod
    def _age_in_hours(backup):
        """Скільки годин минуло з моменту копії; None -- якщо копій немає.

        SQLite віддає created_at без часового поясу, PostgreSQL -- з ним,
        тож наївне значення трактуємо як UTC: інакше відніманням упало б.
        """
        if backup is None or backup.created_at is None:
            return None
        created = backup.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - created
        return delta.total_seconds() / 3600
