from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class Trainer(TimestampMixin, db.Model):
    __tablename__ = 'trainers'

    id = db.Column(BigIntPK, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False, index=True)
    # ПІБ у давальному відмінку для лекторського серта ("Гусак Валерії").
    # Автовідмінювання ненадійне -> зберігаємо вручну.
    full_name_dative = db.Column(db.String(200))
    slug = db.Column(db.String(200), unique=True, nullable=False)
    role = db.Column(db.String(300))
    bio = db.Column(db.Text)
    photo = db.Column(db.String(500))
    # Підпис тренера (шлях відносно static) -- друкується на сертифікатах
    # його заходів. Напр. "images/trainers/<slug>/signature.webp".
    signature = db.Column(db.String(500))
    experience_years = db.Column(db.Integer)
    # Email тренера -- для admin-нотифікації про реєстрацію/скасування на
    # його захід (NotificationRule.notify_event_trainer). Nullable, бо
    # історично тренерів додавали без контактної пошти.
    email = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, index=True)

    # Опційні регалії (показуються публічно лише якщо заповнені):
    #   certificates -- [{url, thumb, caption}] завантажені зображення (lightbox)
    #   patents      -- [{label, url}] активні гіперпосилання (винаходи/патенти)
    #   articles     -- [{label, url}] посилання на наукові статті
    certificates = db.Column(db.JSON, default=list)
    patents = db.Column(db.JSON, default=list)
    articles = db.Column(db.JSON, default=list)
    # Наукова та дослідницька діяльність -- список текстових пунктів.
    research = db.Column(db.JSON, default=list)
    # Додаткові секції профілю (списки текстових пунктів, один рядок = пункт):
    #   skills               -- професійні навички (рядок із ":" -> підзаголовок)
    #   education            -- освіта та кваліфікація (рядок із роком -> timeline)
    #   additional_education -- додаткова освіта та стажування (timeline)
    #   work_experience      -- досвід роботи (timeline)
    skills = db.Column(db.JSON, default=list)
    education = db.Column(db.JSON, default=list)
    additional_education = db.Column(db.JSON, default=list)
    work_experience = db.Column(db.JSON, default=list)

    __table_args__ = (
        db.CheckConstraint(
            'experience_years >= 0',
            name='ck_trainers_experience_non_negative',
        ),
    )

    courses = db.relationship(
        'Course',
        foreign_keys='Course.trainer_id',
        back_populates='trainer',
        lazy='dynamic',
    )

    def __repr__(self):
        return f'<Trainer {self.full_name}>'
