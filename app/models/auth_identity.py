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

from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


class AuthIdentity(TimestampMixin, db.Model):
    __tablename__ = 'auth_identities'

    PROVIDER_PASSWORD = 'password'
    PROVIDER_GOOGLE = 'google'
    PROVIDER_APPLE = 'apple'
    PROVIDERS = (PROVIDER_PASSWORD, PROVIDER_GOOGLE, PROVIDER_APPLE)

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
            "provider IN ('password', 'google', 'apple')",
            name='ck_auth_identities_provider',
        ),
    )

    @classmethod
    def find_by_provider_sub(cls, provider, sub):
        """Знайти identity за (provider, sub). Повертає None, якщо нема."""
        return cls.query.filter_by(provider=provider, provider_sub=str(sub)).first()

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

    def touch(self):
        """Оновити last_used_at до зараз. Викликається після успішного логіну."""
        self.last_used_at = datetime.now(timezone.utc)

    def __repr__(self):
        return f'<AuthIdentity {self.provider}/{self.email or self.provider_sub}>'
