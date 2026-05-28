import base64
import hashlib
import logging
import re

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from app.extensions import db
from app.models.mixins import TimestampMixin

GA_ID_RE = re.compile(r'^G-[A-Z0-9]{4,20}$')

logger = logging.getLogger(__name__)


def _get_fernet():
    secret = current_app.config['SECRET_KEY']
    key = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


class SiteSettings(TimestampMixin, db.Model):
    """Singleton: site-wide settings stored in DB, managed via admin panel."""
    __tablename__ = 'site_settings'

    id = db.Column(db.Integer, primary_key=True, default=1)

    # Company info
    company_name = db.Column(db.String(100), default='ІПРМ')
    company_full_name = db.Column(
        db.String(500),
        default='Інститут Плазмотерапії та Регенеративної Медицини',
    )
    company_legal_name = db.Column(db.String(500), default='ПО "ІПРМ"')
    edrpou = db.Column(db.String(20), default='45871060')

    # Contacts
    phone_primary = db.Column(db.String(50), default='+380670050707')
    phone_secondary = db.Column(db.String(50), default='+380 96 090 0007')
    email = db.Column(db.String(255), default='office@iprm.com')
    address = db.Column(
        db.Text,
        default='02002, Україна, місто Київ, вулиця Микільсько-слобідська, будинок 2б, квартира 246',
    )
    city = db.Column(db.String(200), default='Київ, Україна')

    # Social media
    facebook_url = db.Column(
        db.String(500),
        default='https://www.facebook.com/profile.php?id=61583812599479',
    )
    instagram_url = db.Column(
        db.String(500),
        default='https://www.instagram.com/Plasmotherapy/',
    )
    telegram_url = db.Column(db.String(500), default='')

    # Business
    business_hours = db.Column(db.String(200), default='Пн-Пт: 09:00-18:00')
    website_url = db.Column(db.String(500), default='https://iprm.space')

    # Секції навігації
    show_labs = db.Column(db.Boolean, default=True)
    show_clinics = db.Column(db.Boolean, default=True)

    # LiqPay
    liqpay_public_key = db.Column(db.String(255), default='')
    liqpay_private_key = db.Column(db.String(255), default='')
    liqpay_sandbox = db.Column(db.Boolean, default=True)

    # Google Analytics 4 Measurement ID (формат "G-XXXXXXXXXX"). Публічний
    # ідентифікатор, що віддається у HTML на кожній сторінці.
    google_analytics_id = db.Column(db.String(50), default='', nullable=False)

    # Google OAuth 2.0 (sign-in). Client ID -- публічний (видно у redirect-
    # URI), client_secret -- Fernet-зашифрований. Якщо обидва порожні --
    # OAuth вимкнено (кнопка "Continue with Google" не показується).
    google_oauth_enabled = db.Column(db.Boolean, default=False, nullable=False)
    google_oauth_client_id = db.Column(db.String(255), default='')
    _google_oauth_client_secret_encrypted = db.Column(
        'google_oauth_client_secret', db.String(500), default=''
    )

    # reCAPTCHA v3 (Google). Site key -- публічний (вшиваємо у HTML),
    # secret key -- шифруємо Fernet. Поріг score 0..1 (нижче = бот).
    recaptcha_enabled = db.Column(db.Boolean, default=False, nullable=False)
    recaptcha_site_key = db.Column(db.String(255), default='')
    _recaptcha_secret_key_encrypted = db.Column(
        'recaptcha_secret_key', db.String(500), default=''
    )
    recaptcha_score_threshold = db.Column(db.Float, default=0.5, nullable=False)

    # Partner integration (MM Medic etc.)
    partner_integration_enabled = db.Column(db.Boolean, default=False, nullable=False)
    _partner_api_key_encrypted = db.Column('partner_api_key', db.String(500), default='')
    _partner_prefill_secret_encrypted = db.Column(
        'partner_prefill_secret', db.String(500), default=''
    )

    # Webhook delivery to partner (e.g. notify mm-medic on event change)
    partner_webhook_enabled = db.Column(db.Boolean, default=False, nullable=False)
    partner_webhook_url = db.Column(db.String(500), default='')
    _partner_webhook_secret_encrypted = db.Column(
        'partner_webhook_secret', db.String(500), default=''
    )

    @property
    def partner_api_key(self):
        if not self._partner_api_key_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(self._partner_api_key_encrypted.encode()).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt partner_api_key')
            return ''

    @partner_api_key.setter
    def partner_api_key(self, value):
        if not value:
            self._partner_api_key_encrypted = ''
            return
        self._partner_api_key_encrypted = _get_fernet().encrypt(value.encode()).decode()

    @property
    def partner_prefill_secret(self):
        if not self._partner_prefill_secret_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(
                self._partner_prefill_secret_encrypted.encode()
            ).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt partner_prefill_secret')
            return ''

    @partner_prefill_secret.setter
    def partner_prefill_secret(self, value):
        if not value:
            self._partner_prefill_secret_encrypted = ''
            return
        self._partner_prefill_secret_encrypted = _get_fernet().encrypt(
            value.encode()
        ).decode()

    @property
    def recaptcha_secret_key(self):
        if not self._recaptcha_secret_key_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(
                self._recaptcha_secret_key_encrypted.encode()
            ).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt recaptcha_secret_key')
            return ''

    @recaptcha_secret_key.setter
    def recaptcha_secret_key(self, value):
        if not value:
            self._recaptcha_secret_key_encrypted = ''
            return
        self._recaptcha_secret_key_encrypted = _get_fernet().encrypt(
            value.encode()
        ).decode()

    @property
    def google_oauth_client_secret(self):
        if not self._google_oauth_client_secret_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(
                self._google_oauth_client_secret_encrypted.encode()
            ).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt google_oauth_client_secret')
            return ''

    @google_oauth_client_secret.setter
    def google_oauth_client_secret(self, value):
        if not value:
            self._google_oauth_client_secret_encrypted = ''
            return
        self._google_oauth_client_secret_encrypted = _get_fernet().encrypt(
            value.encode()
        ).decode()

    @property
    def is_google_oauth_configured(self):
        """OAuth готовий до використання: enabled + є client_id і secret."""
        return bool(
            self.google_oauth_enabled
            and self.google_oauth_client_id
            and self.google_oauth_client_secret
        )

    @property
    def partner_webhook_secret(self):
        if not self._partner_webhook_secret_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(
                self._partner_webhook_secret_encrypted.encode()
            ).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt partner_webhook_secret')
            return ''

    @partner_webhook_secret.setter
    def partner_webhook_secret(self, value):
        if not value:
            self._partner_webhook_secret_encrypted = ''
            return
        self._partner_webhook_secret_encrypted = _get_fernet().encrypt(
            value.encode()
        ).decode()

    @property
    def effective_google_analytics_id(self):
        """GA Measurement ID -- спершу з БД, інакше з config (env-var).
        Порожній рядок => GA вимкнено."""
        if self.google_analytics_id:
            return self.google_analytics_id
        return current_app.config.get('GOOGLE_ANALYTICS_ID', '') or ''

    @staticmethod
    def is_valid_ga_id(value):
        """GA4 Measurement ID має формат G-XXXXXXXXXX. Порожній рядок
        вважається валідним (означає вимкнення)."""
        if not value:
            return True
        return bool(GA_ID_RE.match(value))

    @classmethod
    def get(cls):
        """Get or create singleton settings row."""
        settings = db.session.get(cls, 1)
        if not settings:
            settings = cls(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings

    def __repr__(self):
        return f'<SiteSettings {self.company_name}>'
