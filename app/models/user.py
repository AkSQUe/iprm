from sqlalchemy import func, select
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class User(TimestampMixin, UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(BigIntPK, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    # Email-verification стан зберігаємо на User-рівні (а не identity),
    # бо це факт про реального власника email, не про конкретний спосіб
    # автентифікації. OAuth-identity-и також мають email_verified --
    # це claim від провайдера, окреме поняття.
    email_confirmed = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    last_login_at = db.Column(db.DateTime(timezone=True))

    # Мова листів користувачу ('uk'/'ru'/'en'); NULL = українська.
    # Заповнюється з активної локалі при реєстрації, змінюється в кабінеті.
    # Рендер листів: flask_babel.force_locale(user.preferred_language or 'uk').
    preferred_language = db.Column(db.String(5))

    # Відписка від НЕОБОВ'ЯЗКОВИХ листів (нагадування тощо). Транзакційні
    # (підтвердження email, відновлення пароля) шлються завжди. Керується
    # посиланням List-Unsubscribe / one-click POST -- див. EmailService.
    email_opt_out = db.Column(db.Boolean, default=False, nullable=False)
    # Стабільний непідбірний токен для лінків відписки (генерується лениво).
    unsubscribe_token = db.Column(db.String(64), unique=True, index=True)

    # Реферальний код учасника (лениво генерується). Префікс 'u' -- щоб коди
    # User і Trainer були глобально унікальні між собою.
    referral_code = db.Column(db.String(32), unique=True, index=True)
    # Серверна атрибуція: код реферера, зафіксований при кліку залогіненим
    # користувачем (переживає втрату cookie/зміну пристрою). Споживається
    # й очищується при створенні реєстрації.
    pending_referral_code = db.Column(db.String(32))
    # Денормалізований баланс реферальних балів (recompute-on-write у
    # referral_service). Швидке читання без SUM; авторитет -- recompute_balance.
    referral_balance = db.Column(db.Integer, default=0, nullable=False, server_default='0')

    # Phase 7 cleanup: усі legacy-колонки (password_hash, user_type,
    # middle_name, birth_date, education, workplace, position, phone,
    # specializations) дропнуто. Canonical джерела:
    #   - password -> AuthIdentity(provider='password').password_hash
    #   - медичні поля -> MedicalProfile.*

    __table_args__ = (
        db.Index('ix_users_created_at', 'created_at'),
    )

    registrations = db.relationship('EventRegistration', back_populates='user', lazy='dynamic')
    created_courses = db.relationship(
        'Course',
        foreign_keys='Course.created_by',
        back_populates='creator',
    )
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

    def __init__(self, email, **kwargs):
        """Construct User зі strip+lower email. Пароль НЕ приймаємо тут
        (після Phase 7 password живе в AuthIdentity, не в User). Для
        створення з паролем -- use User.create_with_password()."""
        # Backward-compat: якщо хтось ще передає password= -- ігноруємо
        # тихо, бо без id неможливо створити identity у __init__.
        kwargs.pop('password', None)
        super().__init__(**kwargs)
        self.email = email.lower().strip()

    def set_password(self, password):
        """Встановити пароль (оновити password-identity).
        Вимагає persisted User (self.id is not None) -- для нових юзерів
        викликайте User.create_with_password() замість __init__+set_password."""
        from app.models.auth_identity import AuthIdentity
        if not self.id:
            raise RuntimeError(
                'set_password() requires a persisted user. '
                'For new users use User.create_with_password().'
            )
        new_hash = generate_password_hash(password)
        ident = AuthIdentity.query.filter_by(
            user_id=self.id,
            provider=AuthIdentity.PROVIDER_PASSWORD,
        ).first()
        if ident:
            ident.password_hash = new_hash
            ident.email = self.email
        else:
            # OAuth-only юзер встановлює пароль вперше -- створюємо identity.
            db.session.add(AuthIdentity(
                user_id=self.id,
                provider=AuthIdentity.PROVIDER_PASSWORD,
                provider_sub=str(self.id),
                email=self.email,
                email_verified=bool(self.email_confirmed),
                password_hash=new_hash,
            ))

    @property
    def has_password(self):
        """Чи заведено пароль (є password-identity).

        Гість після покупки -- користувач БЕЗ неї: акаунт існує, входу ще
        немає. Саме цей стан відрізняє "запропонувати створити кабінет" від
        "запропонувати увійти".
        """
        from app.models.auth_identity import AuthIdentity
        if not self.id:
            return False
        return AuthIdentity.query.filter_by(
            user_id=self.id, provider=AuthIdentity.PROVIDER_PASSWORD,
        ).first() is not None

    def check_password(self, password):
        """Перевірка пароля. Дивимось у password-identity. Юзер без
        password-identity (OAuth-only, ще не встановив) -- завжди False."""
        from app.models.auth_identity import AuthIdentity
        if not self.id:
            return False
        ident = AuthIdentity.query.filter_by(
            user_id=self.id,
            provider=AuthIdentity.PROVIDER_PASSWORD,
        ).first()
        if not ident or not ident.password_hash:
            return False
        return check_password_hash(ident.password_hash, password)

    @classmethod
    def create_with_password(cls, email, password, **user_kwargs):
        """Створити User + password-identity + порожній MedicalProfile в
        одній транзакції. НЕ комітить -- caller робить commit (щоб
        поєднати з email-token, audit-log тощо).

        Прокидує додаткові kwargs у конструктор User (first_name,
        last_name, email_confirmed, is_active, ...)."""
        from app.models.auth_identity import AuthIdentity
        from app.models.medical_profile import MedicalProfile

        user = cls(email=email, **user_kwargs)
        db.session.add(user)
        db.session.flush()  # призначає user.id без commit

        db.session.add(AuthIdentity(
            user_id=user.id,
            provider=AuthIdentity.PROVIDER_PASSWORD,
            provider_sub=str(user.id),
            email=user.email,
            email_verified=bool(user_kwargs.get('email_confirmed', False)),
            password_hash=generate_password_hash(password),
        ))
        db.session.add(MedicalProfile(
            user_id=user.id,
            source=MedicalProfile.SOURCE_SELF,
        ))
        return user

    @classmethod
    def create_with_oauth(cls, provider, sub, email, email_verified=False,
                          first_name=None, last_name=None, raw_claims=None):
        """Створити User через OAuth-провайдера (Phase 3+). Створює
        User + AuthIdentity(provider=<...>) + порожній MedicalProfile.
        Password-identity НЕ створюється -- юзер логіниться лише через
        OAuth (або встановить пароль пізніше через "Забули пароль")."""
        from app.models.auth_identity import AuthIdentity
        from app.models.medical_profile import MedicalProfile

        user = cls(
            email=email,
            first_name=first_name or '',
            last_name=last_name or '',
            email_confirmed=bool(email_verified),
        )
        db.session.add(user)
        db.session.flush()

        db.session.add(AuthIdentity(
            user_id=user.id,
            provider=provider,
            provider_sub=str(sub),
            email=email,
            email_verified=bool(email_verified),
            raw_claims=raw_claims,
        ))
        db.session.add(MedicalProfile(
            user_id=user.id,
            source=MedicalProfile.SOURCE_SELF,
        ))
        return user

    def get_unsubscribe_token(self):
        """Повернути (за потреби -- згенерувати й зберегти) стабільний токен
        для посилань відписки. Робить flush, але не commit."""
        import secrets
        if not self.unsubscribe_token:
            self.unsubscribe_token = secrets.token_urlsafe(32)
            db.session.add(self)
            db.session.flush()
        return self.unsubscribe_token

    def get_referral_code(self):
        """Повернути (за потреби -- згенерувати) реферальний код учасника.
        Робить flush, але не commit."""
        from app.services.referral_service import ensure_referral_code
        return ensure_referral_code(self, prefix='u')

    @property
    def full_name(self):
        """ПІБ у канонічному порядку: Прізвище Ім'я По-батькові.
        По-батькові живе у MedicalProfile (Phase 1+); якщо профілю нема
        чи поле порожнє -- лише Прізвище Ім'я."""
        parts = [self.last_name, self.first_name]
        if self.medical_profile and self.medical_profile.middle_name:
            parts.append(self.medical_profile.middle_name)
        return ' '.join(p for p in parts if p)

    @property
    def specialization_labels(self):
        """Список людських назв спеціалізацій. Делегує у MedicalProfile."""
        if self.medical_profile:
            return self.medical_profile.specialization_labels
        return []

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
