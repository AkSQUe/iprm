import base64
import hashlib
import logging
import re

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from app.extensions import db
from app.models.mixins import TimestampMixin, TranslatableMixin, utcnow

GA_ID_RE = re.compile(r'^G-[A-Z0-9]{4,20}$')

logger = logging.getLogger(__name__)


def _get_fernet():
    secret = current_app.config['SECRET_KEY']
    key = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


class SiteSettings(TranslatableMixin, TimestampMixin, db.Model):
    """Singleton: site-wide settings stored in DB, managed via admin panel."""
    __tablename__ = 'site_settings'
    # Публічні брендові тексти; юридичні/банківські реквізити -- лише укр.
    __translatable__ = (
        'company_name', 'company_full_name', 'address', 'city', 'business_hours',
    )

    id = db.Column(db.Integer, primary_key=True, default=1)

    # Company info
    company_name = db.Column(db.String(100), default='ІПРМ')
    company_full_name = db.Column(
        db.String(500),
        default='Інститут Плазмотерапії та Регенеративної Медицини',
    )
    company_legal_name = db.Column(db.String(500), default='ПО "ІПРМ"')
    edrpou = db.Column(db.String(20), default='45871060')

    # Банківські реквізити -- для рахунка на оплату (invoice_service).
    bank_iban = db.Column(
        db.String(34), default='UA213052990000026003006239637', nullable=False,
    )
    bank_name = db.Column(
        db.String(255), default='АТКБ «ПРИВАТБАНК»', nullable=False,
    )
    tax_status = db.Column(
        db.String(255),
        default='Платник єдиного податку третьої групи (неплатник ПДВ)',
        nullable=False,
    )

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
    # Рік заснування -- для лічильника "років досвіду" на Головній.
    founding_year = db.Column(db.Integer, default=2015, nullable=False, server_default='2015')

    # Секції навігації
    show_labs = db.Column(db.Boolean, default=True)
    show_clinics = db.Column(db.Boolean, default=True)

    # LiqPay. Public key -- відкритий ідентифікатор, plaintext. Private
    # key -- секрет з доступом до коштів; зберігаємо Fernet-зашифрованим
    # (як recaptcha/apple/partner). DB-колонка лишається 'liqpay_private_key'
    # для сумісності з env-fallback у services/liqpay.py.
    liqpay_public_key = db.Column(db.String(255), default='')
    _liqpay_private_key_encrypted = db.Column(
        'liqpay_private_key', db.String(500), default=''
    )
    liqpay_sandbox = db.Column(db.Boolean, default=True)
    # Rotation reminders -- timestamp коли секрет востаннє оновлювали.
    liqpay_private_key_set_at = db.Column(db.DateTime(timezone=True))

    # Google Analytics 4 Measurement ID (формат "G-XXXXXXXXXX"). Публічний
    # ідентифікатор, що віддається у HTML на кожній сторінці.
    google_analytics_id = db.Column(db.String(50), default='', nullable=False)

    # Реєстраційний номер провайдера БПР (4 цифри) -- сегмент номера
    # сертифіката (формат РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ).
    bpr_provider_number = db.Column(db.String(20), default='', nullable=False)

    # Формат (розмір) сертифіката: 'a4' (210x297) або 'compact' (180x240).
    # Макет ідентичний -- готовий канвас масштабується під обрану сторінку.
    certificate_format = db.Column(db.String(20), default='a4', nullable=False)

    # Плаваючий блок "найближчі заходи" на публічних сторінках (2 найближчі
    # майбутні проведення). Користувач може закрити (стан -- у localStorage).
    show_upcoming_events = db.Column(db.Boolean, default=False, nullable=False)

    # Вигляд блоку "найближчі заходи": 'popup' (плаваючий знизу зліва) або
    # 'bar' (закріплена плашка під шапкою на всю ширину).
    upcoming_events_style = db.Column(db.String(10), default='popup', nullable=False)

    # Поріг "мало місць": коли вільних місць на проведенні <= порога,
    # лічильник "Залишилось N місць" підсвічується попереджувальним стилем.
    seats_low_threshold = db.Column(db.Integer, default=5, nullable=False)

    # ROI-калькулятор окупності на сторінці курсу (Блок 6, референс Multimed).
    show_roi_calculator = db.Column(db.Boolean, default=True, nullable=False)

    # Авто-email "заповніть дані для сертифіката": за скільки днів до заходу
    # нагадувати учасникам з незаповненою МОЗ-анкетою. 0 -- вимкнено.
    certdata_reminder_days = db.Column(db.Integer, default=3, nullable=False)

    # Google OAuth 2.0 (sign-in). Client ID -- публічний (видно у redirect-
    # URI), client_secret -- Fernet-зашифрований. Якщо обидва порожні --
    # OAuth вимкнено (кнопка "Continue with Google" не показується).
    google_oauth_enabled = db.Column(db.Boolean, default=False, nullable=False)
    google_oauth_client_id = db.Column(db.String(255), default='')
    _google_oauth_client_secret_encrypted = db.Column(
        'google_oauth_client_secret', db.String(500), default=''
    )
    google_oauth_client_secret_set_at = db.Column(db.DateTime(timezone=True))

    # Apple Sign In (Phase 5). На відміну від Google, client_secret -- це
    # короткий JWT, що генерується на льоту з team_id + services_id +
    # key_id + ES256-підписом приватним ключем (.p8 з developer.apple.com).
    # Приватний ключ -- PEM-блок ~300 байт; шифруємо Fernet. Усе інше --
    # публічні ідентифікатори (видно у HTML/URLs).
    apple_signin_enabled = db.Column(db.Boolean, default=False, nullable=False)
    apple_team_id = db.Column(db.String(50), default='')
    apple_services_id = db.Column(db.String(255), default='')
    apple_key_id = db.Column(db.String(50), default='')
    _apple_private_key_encrypted = db.Column(
        'apple_private_key', db.Text, default=''
    )
    apple_private_key_set_at = db.Column(db.DateTime(timezone=True))

    # reCAPTCHA v3 (Google). Site key -- публічний (вшиваємо у HTML),
    # secret key -- шифруємо Fernet. Поріг score 0..1 (нижче = бот).
    recaptcha_enabled = db.Column(db.Boolean, default=False, nullable=False)
    recaptcha_site_key = db.Column(db.String(255), default='')
    _recaptcha_secret_key_encrypted = db.Column(
        'recaptcha_secret_key', db.String(500), default=''
    )
    recaptcha_score_threshold = db.Column(db.Float, default=0.5, nullable=False)
    recaptcha_secret_key_set_at = db.Column(db.DateTime(timezone=True))

    # Глобальний пул менеджерських email-ів. На цей список посилається
    # прапор notify_managers у NotificationRule -- адмін веде його один раз
    # і вмикає/вимикає в потрібних подіях.
    event_manager_emails = db.Column(db.JSON, default=list, nullable=False)

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

    # MM Medic consumable-materials reservation API (outgoing, request/response).
    # Signs requests with the SAME shared HMAC secret as the webhook
    # (partner_webhook_secret) -- no separate secret needed.
    mm_medic_integration_enabled = db.Column(db.Boolean, default=False, nullable=False)
    mm_medic_api_base_url = db.Column(db.String(500), default='')

    # Реферальна програма. Кожен учасник/тренер має власний реферальний код;
    # за оплачену реєстрацію по його посиланню нараховуються бонусні бали
    # лояльності (окремі від балів БПР). Поки лише накопичення (без витрати).
    # TODO(redemption): витрата балів (знижка на курс) + двостороння знижка
    #   приведеному покупцю -- окрема фаза, потребує рішень (курс бал->грн,
    #   макс. % покриття, повернення балів при refund).
    referral_enabled = db.Column(db.Boolean, default=False, nullable=False)
    # Скільки бонусних балів нараховувати рефереру за одну оплачену реєстрацію.
    referral_points_per_paid = db.Column(db.Integer, default=1, nullable=False)
    # Термін дії cookie атрибуції (днів). Скільки часу тримається "хто привів".
    referral_cookie_days = db.Column(db.Integer, default=60, nullable=False)
    # Модель атрибуції: 'last' -- останній клік перезаписує; 'first' -- перший
    # клік закріплюється (наступні ?ref= не перезаписують cookie).
    referral_attribution = db.Column(
        db.String(10), default='last', nullable=False, server_default='last',
    )
    # Період "дозрівання" балів (днів): нараховані бали лежать у 'pending' і
    # стають активними ('granted') лише через N днів (антифрод проти
    # refund-фарму). 0 -- активуються одразу.
    referral_maturity_days = db.Column(
        db.Integer, default=0, nullable=False, server_default='0',
    )
    # Стеля активних нарахувань на одного реферера. 0 -- без ліміту.
    referral_max_per_referrer = db.Column(
        db.Integer, default=0, nullable=False, server_default='0',
    )
    # Чи слати рефереру лист про нарахування балів.
    referral_notify_referrer = db.Column(
        db.Boolean, default=True, nullable=False, server_default=db.true(),
    )

    __table_args__ = (
        db.CheckConstraint(
            "referral_attribution IN ('first', 'last')",
            name='ck_site_settings_referral_attribution',
        ),
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
            self.recaptcha_secret_key_set_at = None
            return
        self._recaptcha_secret_key_encrypted = _get_fernet().encrypt(
            value.encode()
        ).decode()
        self.recaptcha_secret_key_set_at = utcnow()

    @property
    def has_recaptcha_secret_key(self):
        """Чи є збережений секрет у БД (без decrypt). Для admin UI --
        показати чи є секрет, не розшифровуючи його даремно."""
        return bool(self._recaptcha_secret_key_encrypted)

    @property
    def liqpay_private_key(self):
        """LiqPay private key (decrypted on read).
        Якщо decrypt fails -- логуємо warning і повертаємо '' (LiqPay
        просто не сконфігурований)."""
        if not self._liqpay_private_key_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(
                self._liqpay_private_key_encrypted.encode()
            ).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt liqpay_private_key')
            return ''

    @liqpay_private_key.setter
    def liqpay_private_key(self, value):
        if not value:
            self._liqpay_private_key_encrypted = ''
            self.liqpay_private_key_set_at = None
            return
        self._liqpay_private_key_encrypted = _get_fernet().encrypt(
            value.encode()
        ).decode()
        self.liqpay_private_key_set_at = utcnow()

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
            self.google_oauth_client_secret_set_at = None
            return
        self._google_oauth_client_secret_encrypted = _get_fernet().encrypt(
            value.encode()
        ).decode()
        self.google_oauth_client_secret_set_at = utcnow()

    @property
    def is_google_oauth_configured(self):
        """OAuth готовий до використання: enabled + є client_id і secret."""
        return bool(
            self.google_oauth_enabled
            and self.google_oauth_client_id
            and self.google_oauth_client_secret
        )

    @property
    def apple_private_key(self):
        """Apple Sign In .p8 приватний ключ (PEM). Розшифровуємо з БД.
        Якщо decrypt fails -- логуємо і повертаємо ''."""
        if not self._apple_private_key_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(
                self._apple_private_key_encrypted.encode()
            ).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt apple_private_key')
            return ''

    @apple_private_key.setter
    def apple_private_key(self, value):
        if not value:
            self._apple_private_key_encrypted = ''
            self.apple_private_key_set_at = None
            return
        self._apple_private_key_encrypted = _get_fernet().encrypt(
            value.encode()
        ).decode()
        self.apple_private_key_set_at = utcnow()

    @property
    def is_apple_signin_configured(self):
        """Apple Sign In готовий: enabled + усі 4 ідентифікатори + ключ."""
        return bool(
            self.apple_signin_enabled
            and self.apple_team_id
            and self.apple_services_id
            and self.apple_key_id
            and self.apple_private_key
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
