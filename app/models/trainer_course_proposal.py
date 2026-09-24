"""Пропозиція курсу/доповіді від тренера (частина «Інформація курсу» анкети).

Переходи статусів -- лише через app.services.trainer_cabinet:
draft -> submitted (тренер), submitted -> accepted | draft (куратор).
Тренер редагує й видаляє тільки чернетку.
"""
from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin


class TrainerCourseProposal(TimestampMixin, db.Model):
    __tablename__ = 'trainer_course_proposals'

    DRAFT = 'draft'
    SUBMITTED = 'submitted'
    ACCEPTED = 'accepted'
    STATUSES = [
        (DRAFT, 'Чернетка'),
        (SUBMITTED, 'Надіслано куратору'),
        (ACCEPTED, 'Прийнято'),
    ]
    STATUS_BADGES = {DRAFT: 'draft', SUBMITTED: 'pending', ACCEPTED: 'active'}
    TITLE_MAX = 120
    THESES_MAX = 10

    id = db.Column(BigIntPK, primary_key=True)
    trainer_id = db.Column(
        db.BigInteger, db.ForeignKey('trainers.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    title = db.Column(db.String(TITLE_MAX), nullable=False)
    theses = db.Column(db.JSON, nullable=False, default=list)
    language = db.Column(db.String(50))
    relevance = db.Column(db.Text)
    target_specialties = db.Column(db.Text)
    resources = db.Column(db.Text)
    future_topics = db.Column(db.Text)
    quiz_url = db.Column(db.String(500))
    status = db.Column(
        db.String(20), nullable=False, default=DRAFT, server_default=DRAFT, index=True,
    )
    curator_comment = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime(timezone=True))

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft', 'submitted', 'accepted')",
            name='ck_trainer_course_proposals_status',
        ),
    )

    trainer = db.relationship('Trainer', back_populates='proposals')

    @property
    def is_editable(self):
        return self.status == self.DRAFT

    @property
    def status_label(self):
        return dict(self.STATUSES).get(self.status, self.status)

    @property
    def status_badge(self):
        return self.STATUS_BADGES.get(self.status, 'draft')
