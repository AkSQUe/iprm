"""Анкета тренера: персональні дані, реквізити ФОП, дані для договору.

Службові дані для куратора. У публічну картку Trainer НЕ синхронізуються:
її редагує контент-редактор (див. специфікацію кабінету тренера).
IBAN, РНОКПП, номер картки й ідентифікаційний код лежать Fernet-шифротекстом.
"""
from app.crypto import encrypted_field
from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin


def _secret_column(name):
    return db.Column(name, db.String(500), nullable=False, default='', server_default='')


class TrainerProfile(TimestampMixin, db.Model):
    __tablename__ = 'trainer_profiles'

    SENSITIVE_FIELDS = ('fop_iban', 'fop_rnokpp', 'card_number', 'tax_id')
    # Підписи для адмінських текстів (лист куратору про зміну реквізитів).
    SENSITIVE_LABELS = {
        'fop_iban': 'IBAN', 'fop_rnokpp': 'РНОКПП',
        'card_number': 'Номер картки', 'tax_id': 'Ідентифікаційний код',
    }
    # Персональні дані для договору: не шифруються, але в адмінці їх видно
    # лише з правом trainers.finance -- без нього поле приховане повністю
    # (маска з 4 символів адреси чи дати нічого корисного не дає).
    PRIVATE_FIELDS = ('birth_date', 'registration_address', 'edrpou')
    REQUIRED_FOR_COMPLETE = (
        'full_name', 'phone', 'email', 'fop_iban', 'fop_rnokpp', 'tax_id',
        'registration_address',
    )

    id = db.Column(BigIntPK, primary_key=True)
    trainer_id = db.Column(
        db.BigInteger, db.ForeignKey('trainers.id', ondelete='CASCADE'),
        nullable=False, unique=True,
    )

    # Контактна інформація
    full_name = db.Column(db.String(200))
    birth_date = db.Column(db.Date)
    education = db.Column(db.Text)
    # Спеціальність за освітою -- окремо від освіти (заклади, роки): у
    # таблиці резюме це своя колонка, у формі БПР -- підписаний рядок у
    # клітинці освіти (окремого рядка бланк не має).
    specialty = db.Column(db.String(255))
    position_titles = db.Column(db.Text)
    workplace = db.Column(db.Text)
    # Професійні сертифікати для резюме, яке подають до реєстру БПР. Один
    # рядок = один сертифікат: саме з рядків PDF-експорт робить перелік у
    # клітинці таблиці. НЕ те саме, що Trainer.certificates -- там зображення
    # дипломів для публічної сторінки тренера.
    professional_certificates = db.Column(db.Text)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(255))
    social_links = db.Column(db.Text)

    # Фото: файлом у медіа-реєстр АБО посиланням на файлообмінник.
    photo_media_id = db.Column(
        db.BigInteger, db.ForeignKey('media_files.id', ondelete='SET NULL'),
        nullable=True,
    )
    photo_url = db.Column(db.String(500))

    # Реквізити ФОП (гонорар -- лише на рахунок ФОП)
    fop_recipient = db.Column(db.String(300))
    _fop_iban = _secret_column('fop_iban')
    _fop_rnokpp = _secret_column('fop_rnokpp')
    fop_payment_purpose = db.Column(db.Text)
    _card_number = _secret_column('card_number')

    # Дані для договору
    _tax_id = _secret_column('tax_id')
    registration_address = db.Column(db.Text)
    edrpou = db.Column(db.String(20))

    fop_iban = encrypted_field('_fop_iban')
    fop_rnokpp = encrypted_field('_fop_rnokpp')
    card_number = encrypted_field('_card_number')
    tax_id = encrypted_field('_tax_id')

    trainer = db.relationship('Trainer', back_populates='profile')
    photo_media = db.relationship('MediaFile', foreign_keys=[photo_media_id])

    @property
    def is_complete(self):
        return all((getattr(self, name) or '').strip() for name in self.REQUIRED_FOR_COMPLETE)

    @property
    def photo_src(self):
        if self.photo_media:
            return self.photo_media.variant_url('card')
        return self.photo_url or None

    @staticmethod
    def mask(value):
        """'•••• 7890' для непорожнього значення; '' для порожнього."""
        value = (value or '').strip()
        return f'•••• {value[-4:]}' if value else ''
