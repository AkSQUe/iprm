from sqlalchemy import func, select
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class User(TimestampMixin, UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(BigIntPK, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    email_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    last_login_at = db.Column(db.DateTime(timezone=True))

    # Поля медичної анкети (МОЗ України №725 п.13). Усі nullable -- історичні
    # користувачі без цих даних мають дозаповнити їх перед реєстрацією на
    # платний захід (валідація на рівні форми, не на рівні БД).
    user_type = db.Column(db.String(20))            # USER_TYPES.keys()
    middle_name = db.Column(db.String(100))          # По батькові
    birth_date = db.Column(db.Date)                  # Дата народження
    education = db.Column(db.String(500))            # «2014, НМУ ім. Богомольця»
    workplace = db.Column(db.String(300))            # Назва ЗОЗу
    position = db.Column(db.String(200))             # Займана посада
    phone = db.Column(db.String(20))                 # Контактний телефон
    # Список codes з SPECIALIZATIONS. JSON -- найгнучкіше для multi-select.
    specializations = db.Column(db.JSON, default=list)

    __table_args__ = (
        db.Index('ix_users_created_at', 'created_at'),
        db.CheckConstraint(
            "user_type IN ('doctor', 'specialist', 'intern', 'student') "
            "OR user_type IS NULL",
            name='ck_users_user_type',
        ),
    )

    USER_TYPES = [
        ('doctor', 'Лікар'),
        ('specialist', 'Молодший спеціаліст з медичною освітою'),
        ('intern', 'Інтерн'),
        ('student', 'Студент'),
    ]

    registrations = db.relationship('EventRegistration', back_populates='user', lazy='dynamic')
    created_courses = db.relationship(
        'Course',
        foreign_keys='Course.created_by',
        back_populates='creator',
    )
    # Phase 1 auth unification: identity-сутності і медпрофіль -- у власних
    # таблицях. Поки що в shadow mode -- колонки User (password_hash,
    # user_type, birth_date, ...) лишаються джерелом істини; нові таблиці
    # читаються/пишуться паралельно. Дроп legacy-колонок -- після Фази 4.
    identities = db.relationship(
        'AuthIdentity',
        back_populates='user',
        cascade='all, delete-orphan',
    )
    medical_profile = db.relationship(
        'MedicalProfile',
        back_populates='user',
        uselist=False,
        cascade='all, delete-orphan',
    )

    def __init__(self, email, password=None, **kwargs):
        super().__init__(**kwargs)
        self.email = email.lower().strip()
        if password:
            self.set_password(password)

    def set_password(self, password):
        """Записати hash пароля. Dual-write на час перехідного періоду
        (Phase 2-7): canonical store -- auth_identities.password_hash;
        users.password_hash лишається як shadow на випадок rollback. Для
        НОВОГО юзера (self.id is None у __init__) -- identity створюється
        у create_with_password() після flush, бо потрібен user.id для FK."""
        new_hash = generate_password_hash(password)
        self.password_hash = new_hash  # shadow write
        if self.id:
            from app.models.auth_identity import AuthIdentity
            ident = AuthIdentity.query.filter_by(
                user_id=self.id,
                provider=AuthIdentity.PROVIDER_PASSWORD,
            ).first()
            if ident:
                ident.password_hash = new_hash
                ident.email = self.email

    def check_password(self, password):
        """Перевірка пароля. Identity-first: дивимось у password-identity
        (canonical після Phase 2); fallback на User.password_hash для
        edge-кейсів (юзер без identity -- напр. створений напряму повз
        фабрику)."""
        from app.models.auth_identity import AuthIdentity
        ident = AuthIdentity.query.filter_by(
            user_id=self.id,
            provider=AuthIdentity.PROVIDER_PASSWORD,
        ).first() if self.id else None
        if ident and ident.password_hash:
            return check_password_hash(ident.password_hash, password)
        if self.password_hash:
            return check_password_hash(self.password_hash, password)
        return False

    @classmethod
    def create_with_password(cls, email, password, **user_kwargs):
        """Створити User + password-identity + порожній MedicalProfile в
        одній транзакції. НЕ комітить -- caller відповідальний за commit
        (щоб поєднати з іншими операціями типу email-token, audit-log).

        Прокидує додаткові kwargs у конструктор User (first_name,
        last_name, email_confirmed, is_active, ...).

        Повертає створений User (з заасайненим id після flush)."""
        from app.extensions import db
        from app.models.auth_identity import AuthIdentity
        from app.models.medical_profile import MedicalProfile

        user = cls(email=email, password=password, **user_kwargs)
        db.session.add(user)
        db.session.flush()  # призначає user.id без commit

        db.session.add(AuthIdentity(
            user_id=user.id,
            provider=AuthIdentity.PROVIDER_PASSWORD,
            provider_sub=str(user.id),
            email=user.email,
            email_verified=bool(user_kwargs.get('email_confirmed', False)),
            password_hash=user.password_hash,
        ))
        db.session.add(MedicalProfile(
            user_id=user.id,
            source=MedicalProfile.SOURCE_SELF,
        ))
        return user

    @property
    def user_type_label(self):
        return dict(self.USER_TYPES).get(self.user_type, self.user_type or '')

    @property
    def full_name(self):
        """ПІБ у канонічному порядку: Прізвище Ім'я По-батькові."""
        parts = [self.last_name, self.first_name, self.middle_name]
        return ' '.join(p for p in parts if p)

    @property
    def specialization_labels(self):
        """Список людських назв спеціалізацій з User.specializations."""
        from app.models.specializations import labels_for_codes
        return labels_for_codes(self.specializations or [])

    @property
    def registration_count(self):
        cached = getattr(self, '_cached_reg_count', None)
        if cached is not None:
            return cached
        return self.registrations.count()

    @classmethod
    def with_registration_count(cls):
        from app.models.registration import EventRegistration
        return (
            select(func.count(EventRegistration.id))
            .where(
                EventRegistration.user_id == cls.id,
                EventRegistration.status.notin_(['cancelled']),
            )
            .correlate(cls)
            .scalar_subquery()
            .label('_registration_count')
        )

    def __repr__(self):
        return f'<User {self.email}>'
