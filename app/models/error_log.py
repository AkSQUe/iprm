"""Модель журналу помилок додатку."""
import json
from datetime import datetime, timezone

from sqlalchemy import Index, func

from app.extensions import db


class ErrorLog(db.Model):
    __tablename__ = 'error_logs'

    id = db.Column(db.BigInteger, primary_key=True)

    error_code = db.Column(db.Integer, nullable=False, index=True)
    error_type = db.Column(db.String(100), nullable=False, index=True)
    error_message = db.Column(db.Text, nullable=False)

    url = db.Column(db.String(500))
    method = db.Column(db.String(10))
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    referrer = db.Column(db.String(500))

    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        index=True,
    )
    user = db.relationship('User', foreign_keys=[user_id])

    traceback = db.Column(db.Text)
    request_data = db.Column(db.Text)
    headers = db.Column(db.Text)

    resolved = db.Column(db.Boolean, default=False, index=True)
    resolved_at = db.Column(db.DateTime(timezone=True))
    resolved_by_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        index=True,
    )
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id])
    resolution_notes = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        Index('idx_error_logs_resolved_created', resolved, created_at.desc()),
    )

    def __repr__(self):
        return f'<ErrorLog {self.id}: {self.error_code} {self.error_type}>'

    def get_request_data(self):
        if self.request_data:
            try:
                return json.loads(self.request_data)
            except Exception:
                return self.request_data
        return None

    def get_headers(self):
        if self.headers:
            try:
                return json.loads(self.headers)
            except Exception:
                return self.headers
        return None

    @classmethod
    def _sanitize_dict(cls, data):
        for key in ('password', 'token', 'secret', 'api_key', 'csrf_token'):
            if key in data:
                data[key] = '***'
        return data

    @classmethod
    def log_error(cls, exception, request=None, user=None, **kwargs):
        """Записати помилку в БД."""
        import traceback as tb_module
        from flask import current_app

        error_log = cls()
        error_log.error_type = exception.__class__.__name__
        error_log.error_message = str(exception)
        error_log.error_code = getattr(exception, 'code', 500)

        if hasattr(exception, '__traceback__') and exception.__traceback__:
            tb_text = ''.join(tb_module.format_exception(
                type(exception), exception, exception.__traceback__,
            ))
            if tb_text.strip() not in ('NoneType: None', 'None'):
                error_log.traceback = tb_text

        if request:
            error_log.url = request.url[:500] if request.url else None
            error_log.method = request.method
            error_log.ip_address = request.remote_addr
            error_log.user_agent = request.user_agent.string
            error_log.referrer = request.referrer

            req_data = {}
            if request.args:
                req_data['args'] = dict(request.args)
            if request.form:
                req_data['form'] = cls._sanitize_dict(dict(request.form))
            if req_data:
                error_log.request_data = json.dumps(req_data, ensure_ascii=False)

            hdrs = dict(request.headers)
            for h in ('Authorization', 'Cookie', 'X-Api-Key'):
                if h in hdrs:
                    hdrs[h] = '***'
            error_log.headers = json.dumps(hdrs, ensure_ascii=False)

        if user and hasattr(user, 'id'):
            error_log.user_id = user.id

        for key, value in kwargs.items():
            if hasattr(error_log, key):
                setattr(error_log, key, value)

        try:
            db.session.add(error_log)
            db.session.commit()
            return error_log
        except Exception as e:
            current_app.logger.error(f'Failed to log error to DB: {e}')
            db.session.rollback()
            return None

    @classmethod
    def get_statistics(cls, days=7):
        from datetime import timedelta
        since = datetime.now(timezone.utc) - timedelta(days=days)

        total = cls.query.filter(cls.created_at >= since).count()
        unresolved = cls.query.filter(
            cls.created_at >= since, cls.resolved.is_(False),
        ).count()

        code_stats = db.session.query(
            cls.error_code, func.count(cls.id),
        ).filter(cls.created_at >= since).group_by(cls.error_code).all()

        return {
            'total_errors': total,
            'unresolved_errors': unresolved,
            'by_code': {str(code): count for code, count in code_stats},
        }
