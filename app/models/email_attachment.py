"""Вкладення листа, збережене для повторної відправки.

Лист із вкладенням (рахунок до оплати, календарне запрошення, сертифікат
учасника чи лектора) збирається з байтів у памʼяті. Автоповтор після
тимчасового збою SMTP і кнопка «переслати» в адмінці збирають лист заново зі
збереженого `EmailLog.html_body` -- і без цього запису йшли б БЕЗ файлу:
людина отримувала «ваш рахунок/сертифікат у вкладенні» з порожнім листом.

Байти (`data`) потрібні лише доти, доки лист може знадобитися відправити
знову: після успіху їх стирають одразу, листу, що не дійшов, лишають на
`ATTACHMENT_FAILED_RETENTION_DAYS` (див. email_service). Сам рядок із
`data IS NULL` не видаляється -- це маркер «вкладення було, але вже стерте»,
за яким повторна відправка чесно відмовляє замість слати лист без файлу.
"""
from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin


class EmailAttachment(TimestampMixin, db.Model):
    __tablename__ = 'email_attachments'

    id = db.Column(BigIntPK, primary_key=True)
    email_log_id = db.Column(
        db.BigInteger,
        db.ForeignKey('email_logs.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(100), nullable=False)
    data = db.Column(db.LargeBinary)

    @property
    def is_purged(self):
        return self.data is None

    def __repr__(self):
        return f'<EmailAttachment {self.id} log={self.email_log_id} {self.filename}>'
