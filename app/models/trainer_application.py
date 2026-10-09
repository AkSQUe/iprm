"""TrainerApplication -- заявка кандидата в тренери зі сторінки /trainers/join.

Лід-форма за зразком B2BRequest: кандидат лишає контакти, досвід у
плазмотерапії й тему, команда веде заявку в /admin/trainer-applications до
рішення, а погодженого кандидата перетворює на тренера (trainer_id).
"""
import re

from sqlalchemy.orm import validates

from app.data.trainer_application_questions import question_by_key
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK

_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class TrainerApplication(TimestampMixin, db.Model):
    __tablename__ = 'trainer_applications'

    id = db.Column(BigIntPK, primary_key=True)

    full_name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    city = db.Column(db.String(120))
    specialty = db.Column(db.String(255), nullable=False)
    workplace = db.Column(db.Text)
    social_links = db.Column(db.Text)
    topic = db.Column(db.Text, nullable=False)
    # [{'key', 'label', 'value'}] -- снапшот на момент подачі: підпис
    # українським джерелом, значення -- код варіанта або текст відповіді.
    answers = db.Column(db.JSON, default=list, nullable=False)
    # Мова, якою кандидат заповнював сторінку: відповідати йому варто нею.
    locale = db.Column(db.String(5), nullable=False, default='uk')

    status = db.Column(db.String(20), default='new', nullable=False, index=True)
    admin_notes = db.Column(db.Text)
    trainer_id = db.Column(
        db.BigInteger, db.ForeignKey('trainers.id', ondelete='SET NULL'),
        nullable=True,
    )
    trainer = db.relationship('Trainer', foreign_keys=[trainer_id])

    __table_args__ = (
        db.Index('ix_trainer_applications_created_at', 'created_at'),
        db.CheckConstraint(
            "status IN ('new', 'in_progress', 'approved', 'rejected')",
            name='ck_trainer_applications_status',
        ),
    )

    STATUSES = [
        ('new', 'Нова'),
        ('in_progress', 'У роботі'),
        ('approved', 'Погоджено'),
        ('rejected', 'Відмова'),
    ]
    # Модифікатор .badge--* на кожен стан (той самий набір, що в EmailLog).
    STATUS_BADGES = {
        'new': 'pending',
        'in_progress': 'info',
        'approved': 'active',
        'rejected': 'cancelled',
    }

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def status_badge(self):
        return self.STATUS_BADGES.get(self.status, 'pending')

    @property
    def answer_rows(self):
        """[(підпис, відповідь)] для адмінки й листа -- українською.

        Код варіанта перекладається підписом із поточного переліку питань;
        якщо питання чи варіанта вже немає, показуємо те, що збережено.
        """
        rows = []
        for item in self.answers or []:
            value = item.get('value') or ''
            question = question_by_key(item.get('key'))
            if question and question['kind'] == 'choice':
                value = dict(question['options']).get(value, value)
            rows.append((item.get('label') or item.get('key') or '', value))
        return rows

    @validates('email')
    def _validate_email(self, _key, value):
        normalized = (value or '').strip().lower()
        if not normalized or len(normalized) > 255 or not _EMAIL_RE.match(normalized):
            raise ValueError(f'невалідний email: {value!r}')
        return normalized

    @validates('status')
    def _validate_status(self, _key, value):
        if value not in {code for code, _ in self.STATUSES}:
            raise ValueError(f'невідомий status: {value!r}')
        return value

    def __repr__(self):
        return f'<TrainerApplication {self.email} {self.status}>'
