"""Database backup model for tracking backup metadata."""
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
    )

    created_by = db.relationship('User', foreign_keys=[created_by_id], lazy='joined')

    def __repr__(self):
        return f'<DatabaseBackup {self.id} {self.backup_type} {self.status}>'

    @property
    def is_restorable(self):
        return self.status == self.STATUS_COMPLETED and self.backup_type != self.TYPE_SCHEMA_ONLY

    @property
    def file_size_display(self):
        if not self.file_size_bytes:
            return '0 B'
        for unit in ('B', 'KB', 'MB', 'GB'):
            if self.file_size_bytes < 1024:
                return f'{self.file_size_bytes:.1f} {unit}'
            self.file_size_bytes /= 1024
        return f'{self.file_size_bytes:.1f} TB'

    @property
    def db_size_display(self):
        if not self.db_size_bytes:
            return '-'
        size = self.db_size_bytes
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024:
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{size:.1f} TB'

    @staticmethod
    def get_statistics():
        from sqlalchemy import func
        total = db.session.query(func.count(DatabaseBackup.id)).scalar() or 0
        completed = db.session.query(func.count(DatabaseBackup.id)).filter(
            DatabaseBackup.status == DatabaseBackup.STATUS_COMPLETED,
        ).scalar() or 0
        total_size = db.session.query(
            func.sum(DatabaseBackup.file_size_bytes),
        ).filter(
            DatabaseBackup.status == DatabaseBackup.STATUS_COMPLETED,
        ).scalar() or 0
        last_backup = (
            DatabaseBackup.query
            .filter(DatabaseBackup.status == DatabaseBackup.STATUS_COMPLETED)
            .order_by(DatabaseBackup.created_at.desc())
            .first()
        )
        return {
            'total': total,
            'completed': completed,
            'failed': total - completed,
            'total_size_bytes': total_size,
            'last_backup': last_backup,
        }
