"""Презентація тренера до конкретного заходу (проведення курсу).

Тренер завантажує файл із кабінету; співробітники (super_admin, admin,
content_editor) отримують лист із посиланням на завантаження в адмінці.

Файл лежить на диску, в `TRAINER_PRESENTATION_FOLDER` (поза app/static і
поза медіа-реєстром): медіа-реєстр приймає лише зображення й перекодовує їх
у WebP, а презентація мусить дійти байт у байт і не бути публічною. У БД --
лише метадані. Запис і видалення файлу -- через
app.services.trainer_presentation_service, не напряму.
"""
from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin


class TrainerPresentation(TimestampMixin, db.Model):
    __tablename__ = 'trainer_presentations'

    id = db.Column(BigIntPK, primary_key=True)
    trainer_id = db.Column(
        db.BigInteger, db.ForeignKey('trainers.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    instance_id = db.Column(
        db.BigInteger, db.ForeignKey('course_instances.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    # Ім'я, під яким файл надіслав тренер (для показу й Content-Disposition).
    original_filename = db.Column(db.String(255), nullable=False)
    # Ім'я на диску -- випадкове, без жодної частини від тренера: ім'я
    # клієнта в шляху файлової системи -- це обхід каталогу.
    stored_name = db.Column(db.String(64), nullable=False, unique=True)
    mimetype = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    uploaded_by_id = db.Column(
        db.BigInteger, db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    # Коли лист співробітникам пішов хоча б одному адресату. NULL -- не
    # пішов (пошта вимкнена, немає адресатів, збій): видно в адмінці.
    notified_at = db.Column(db.DateTime(timezone=True))

    trainer = db.relationship('Trainer')
    instance = db.relationship('CourseInstance')
    uploaded_by = db.relationship('User')

    @property
    def size_label(self):
        """Розмір для людини: '3,4 МБ' / '812 КБ'."""
        size = self.size_bytes or 0
        if size >= 1024 * 1024:
            return f'{size / (1024 * 1024):.1f} МБ'.replace('.', ',')
        return f'{max(1, round(size / 1024))} КБ'
