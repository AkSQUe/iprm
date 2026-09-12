"""AuthIdentity -- спосіб логіну користувача.

Один User може мати кілька identity (password + Google + Apple). Сама
ідентичність користувача -- це рядок у `users`; цей запис каже, ЯК він
може автентифікуватись.

Для provider='password' -- password_hash зберігається тут; provider_sub
дорівнює str(user_id) (стабільний sub нашої власної "провайдер-системи").
Для OAuth -- password_hash порожній; provider_sub = `sub` з OIDC-claims
(стабільний ID від провайдера), у raw_claims кешуємо корисні поля
(email_verified, given_name, family_name, locale).

UNIQUE(provider, provider_sub) гарантує, що одна Google-учётка не може
бути прив'язана до двох наших User. INDEX(provider, email) -- для
identity-first логіну за паролем ("чи є password-identity з email
john@gmail.com").
"""
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class AuthIdentity(TimestampMixin, db.Model):
    __tablename__ = 'auth_identities'

    PROVIDER_PASSWORD = 'password'
    PROVIDER_GOOGLE = 'google'
    PROVIDER_APPLE = 'apple'
    # Партнерський сайт (mm-medic) завів акаунт за prefill-токеном.
    # Не спосіб входу, а маркер походження: password_hash порожній, тож
    # людина або встановлює пароль, або входить через OAuth. Потрібен,
    # щоб форма реєстрації могла назвати джерело акаунта.
    PROVIDER_PARTNER = 'partner'
    PROVIDERS = (PROVIDER_PASSWORD, PROVIDER_GOOGLE, PROVIDER_APPLE,
                 PROVIDER_PARTNER)
    # Провайдери, якими справді МОЖНА увійти. PROVIDERS ширший: partner --
    # маркер походження акаунта, а не спосіб автентифікації. Різниця
    # критична там, де рахують "чи лишиться людині чим увійти": лічильник
    # усіх рядків підряд дозволяв зняти останній справжній спосіб входу.
    LOGIN_PROVIDERS = (PROVIDER_PASSWORD, PROVIDER_GOOGLE, PROVIDER_APPLE)

    id = db.Column(BigIntPK, primary_key=True)
    user_id = db.Column(
        BigIntPK,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    provider = db.Column(db.String(20), nullable=False)
    provider_sub = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255))
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    # Тільки для provider='password'. Для OAuth -- NULL.
    password_hash = db.Column(db.String(255))
    # Останні OIDC-claims (мінімально потрібні: email, email_verified,
    # given_name, family_name, locale). Не зберігаємо токени доступу.
    raw_claims = db.Column(db.JSON)
    last_used_at = db.Column(db.DateTime(timezone=True))

    user = db.relationship('User', back_populates='identities')

    __table_args__ = (
        db.UniqueConstraint(
            'provider', 'provider_sub',
            name='uq_auth_identities_provider_sub',
        ),
        db.Index(
            'ix_auth_identities_provider_email',
            'provider', 'email',
        ),
        db.CheckConstraint(
            "provider IN ('password', 'google', 'apple', 'partner')",
            name='ck_auth_identities_provider',
        ),
    )

    @classmethod
    def find_by_provider_sub(cls, provider, sub):
        """Знайти identity за (provider, sub). Повертає None, якщо нема."""
        return cls.query.filter_by(provider=provider, provider_sub=str(sub)).first()

    @classmethod
    def find_partner(cls, user_id):
        """Маркер партнерського походження акаунта; None, якщо його нема."""
        return cls.query.filter_by(
            user_id=user_id, provider=cls.PROVIDER_PARTNER,
        ).first()

    @classmethod
    def attach_partner(cls, user, issuer):
        """Позначити акаунт як заведений партнером. Ідемпотентно.

        provider_sub -- str(user.id), як у password-identity: прив'язка до
        email робила рядок несумісним із власним акаунтом після зміни
        адреси, і наступний prefill зі старою адресою впирався в
        UNIQUE(provider, provider_sub).

        IntegrityError ковтаємо свідомо: двоє одночасних prefill проходять
        перевірку "рядка ще нема" обидва, і другий INSERT падає. Рядок при
        цьому вже існує -- робота зроблена, і віддавати 500 зі сторінки
        реєстрації немає за що.

        Вставка -- у SAVEPOINT, а не в основній транзакції: голий
        session.rollback() відкотив би ВСЕ незакомічене, разом зі змінами,
        які встиг зробити викликач (той-таки email_confirmed, що його
        ставлять рядком вище). Відкочується лише сама невдала вставка.
        """
        existing = cls.find_partner(user.id)
        if existing is not None:
            return existing

        try:
            with db.session.begin_nested():
                identity = cls(
                    user_id=user.id,
                    provider=cls.PROVIDER_PARTNER,
                    provider_sub=str(user.id),
                    email=user.email,
                    email_verified=bool(user.email_confirmed),
                    raw_claims={'issuer': issuer},
                )
                db.session.add(identity)
        except IntegrityError:
            return cls.find_partner(user.id)
        return identity

    @classmethod
    def count_login_methods(cls, user_id):
        """Скільки в юзера СПРАВЖНІХ способів увійти.

        Порожня password-identity (хеша немає -- OAuth-юзер, який пароля
        ще не ставив) не рахується: увійти нею не можна. Так само вважає
        сторінка /auth/account/connections, коли вирішує, чи показувати
        кнопку "Встановити пароль".
        """
        return cls.query.filter(
            cls.user_id == user_id,
            cls.provider.in_(cls.LOGIN_PROVIDERS),
            db.or_(cls.provider != cls.PROVIDER_PASSWORD,
                   cls.password_hash.isnot(None)),
        ).count()

    @classmethod
    def find_password_identity_by_email(cls, email):
        """Знайти password-identity за email -- identity-first lookup для
        входу з паролем (app/auth/routes.py)."""
        if not email:
            return None
        return cls.query.filter_by(
            provider=cls.PROVIDER_PASSWORD,
            email=email.lower().strip(),
        ).first()

    def check_password(self, password):
        """Перевірити пароль цієї identity. Для OAuth-identity (без хеша)
        -- завжди False. Викликається, коли identity вже знайдено, щоб не
        робити повторний запит через User.check_password()."""
        from werkzeug.security import check_password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def touch(self):
        """Оновити last_used_at до зараз. Викликається після успішного логіну."""
        self.last_used_at = datetime.now(timezone.utc)

    def __repr__(self):
        return f'<AuthIdentity {self.provider}/{self.email or self.provider_sub}>'
