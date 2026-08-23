import base64
import hashlib
import logging
import re

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from app.extensions import db
from app.models.mixins import TimestampMixin, TranslatableMixin, utcnow

GA_ID_RE = re.compile(r'^G-[A-Z0-9]{4,20}$')
# Meta Pixel ID -- числовий, наразі 15-16 цифр. Строгий формат ловить
# найчастішу помилку: у поле вставляють увесь snippet замість самого ID.
META_PIXEL_ID_RE = re.compile(r'^[0-9]{15,16}$')
# PostHog Project API Key -- завжди префікс 'phc_' + base62-хвіст. Строгий
# префікс ловить найчастішу плутанину: у поле вставляють Personal API Key
# ('phx_...'), який дає доступ до читання даних проєкту і в HTML йому не місце.
POSTHOG_KEY_RE = re.compile(r'^phc_[A-Za-z0-9_-]{20,60}$')

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

    # Meta (Facebook) Pixel. ID публічний -- віддається у HTML на кожній
    # сторінці. Прапорець окремо від ID навмисно: вимкнути трекінг треба вміти
    # миттєво (домен/consent/інцидент), не стираючи сам ID.
    meta_pixel_enabled = db.Column(db.Boolean, default=False, nullable=False)
    meta_pixel_id = db.Column(db.String(50), default='', nullable=False)

    # PostHog (product analytics + session replay). Project API Key публічний
    # -- він і так їде у HTML кожної сторінки, тож не шифрується.
    #
    # Прапорці NULLABLE, і NULL тут значуще: "в адмінці не задано, вирішує
    # env". Без цієї тристанності прапорець БД мовчки ігнорувався, коли ключ
    # приходив з env -- а на проді він приходить саме звідти. Адміністратор
    # знімав галку, бачив "Збережено" і далі слав дані; поставити галку
    # реплею так само не давало нічого. Аварійний рубильник на сайті з
    # медданими зобов'язаний діяти незалежно від того, звідки взявся ключ.
    #
    # Прапорців три, і жоден не надмірність: posthog_enabled гасить усю
    # аналітику, posthog_session_recording -- САМЕ запис екрана (реплей
    # знімає на відео картки учасників, і гасити його треба вміти, не
    # осліплюючи заразом статистику), posthog_exclude_admin прибирає адмінку
    # з-під збору цілком -- iprm_section дає фільтр у звітах, але квоту
    # подій усе одно витрачає.
    posthog_enabled = db.Column(db.Boolean, nullable=True)
    posthog_project_api_key = db.Column(db.String(60), default='', nullable=False)
    posthog_session_recording = db.Column(db.Boolean, nullable=True)
    posthog_exclude_admin = db.Column(db.Boolean, nullable=True)

    # Реєстраційний номер провайдера БПР (4 цифри) -- сегмент номера
    # сертифіката (формат РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ).
    bpr_provider_number = db.Column(db.String(20), default='', nullable=False)

    # Лічильники останнього виданого сегмента "номер учасника" -- окремо для
    # участницьких і лекторських сертифікатів (у лекторських свій діапазон
    # 1xxxxx через LECTURER_NUMBER_OFFSET).
    #
    # Раніше цей сегмент брався як COUNT(*) + 1 по таблиці сертифікатів. Це
    # мало два режими відмови: (1) двоє одночасних видач отримували той самий
    # номер, і retry-петля не сходилась, бо перераховувала ТУ САМУ кількість;
    # (2) після видалення будь-якого сертифіката лічильник ішов назад і
    # колізія ставала постійною. Монотонний лічильник знімає обидва: номер
    # ніколи не повторюється, навіть після видалення рядків.
    #
    # Значення видаються під блокуванням рядка (див. app/services/
    # certificate_service.py -> _allocate_number). НЕ правити вручну: зменшення
    # призведе до колізій з уже виданими номерами.
    bpr_participant_counter = db.Column(
        db.Integer, default=0, server_default='0', nullable=False,
    )
    bpr_lecturer_counter = db.Column(
        db.Integer, default=0, server_default='0', nullable=False,
    )

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

    # Фонове відео у hero Головної. Вимкнення повертає hero до вигляду до
    # впровадження відео: ні відео, ні постера -- лише світле тло.
    show_home_hero_video = db.Column(db.Boolean, default=True, nullable=False)

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

    # Приймання замірів швидкості (tools/perf/perf_check.py --push). Окремий
    # ключ, а не partner_api_key: у партнерської інтеграції інша зона довіри,
    # і ротація одного не повинна ламати інше. Порожній ключ = приймання
    # вимкнено (ендпоінт віддає 404).
    _perf_api_key_encrypted = db.Column('perf_api_key', db.String(500), default='')
    perf_api_key_set_at = db.Column(db.DateTime(timezone=True))

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

    # Промокод-подяка: персональна знижка на НАСТУПНИЙ курс, яка видається
    # автоматично разом з листом "оплату підтверджено". Сенс -- дати причину
    # повернутись на сайт: лист про оплату інакше є глухим кутом.
    # Код одноразовий і має термін дії (дедлайн -- те, що змушує діяти).
    thankyou_promo_enabled = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.false(),
    )
    # Знижка у відсотках. Лише percent: фіксована сума на курсах з різною
    # ціною поводиться непередбачувано (на дешевому курсі це 100%).
    thankyou_promo_percent = db.Column(
        db.Integer, default=10, nullable=False, server_default='10',
    )
    # Скільки днів діє виданий код.
    thankyou_promo_days = db.Column(
        db.Integer, default=30, nullable=False, server_default='30',
    )

    # Sintegrum -- зовнішня LMS, де фізично відбувається навчання на
    # онлайн-курсах. ІПРМ дзеркалить її каталог треків, продає доступ і
    # віддає учаснику посилання на навчання. Ключ -- Bearer-секрет, тому
    # шифруємо Fernet, як і решту секретів із доступом до чужих систем.
    # Аліас компанії -- те, що підставляється в шлях /external/{company}/...
    sintegrum_enabled = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.false(),
    )
    # Чи показувати розділ онлайн-курсів у публічній навігації. Окремо від
    # sintegrum_enabled: каталог можна наповнювати й готувати, поки розділ
    # ще не видно відвідувачам. Той самий підхід, що show_labs/show_clinics.
    show_online_courses = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.false(),
    )
    sintegrum_api_base_url = db.Column(
        db.String(500), default='https://api.sintegrum.com',
        server_default='https://api.sintegrum.com', nullable=False,
    )
    sintegrum_company_alias = db.Column(
        db.String(100), default='', server_default='', nullable=False,
    )
    _sintegrum_api_key_encrypted = db.Column(
        'sintegrum_api_key', db.String(500), default='', server_default='',
    )
    sintegrum_api_key_set_at = db.Column(db.DateTime(timezone=True))
    # Періодичність фонової синхронізації каталогу.
    sintegrum_sync_interval_minutes = db.Column(
        db.Integer, default=60, nullable=False, server_default='60',
    )
    # Скільки живе видане учаснику посилання на навчання. Саме воно і є
    # "тимчасовим": ціль редіректу (посилання реєстрації в Sintegrum)
    # безстрокова й спільна, тому назовні вона не показується.
    sintegrum_access_ttl_hours = db.Column(
        db.Integer, default=72, nullable=False, server_default='72',
    )
    # Через скільки днів нагадати покупцю, що доступ відкрито, а він жодного
    # разу не заходив. 0 -- не нагадувати (так само, як certdata_reminder_days).
    sintegrum_access_reminder_days = db.Column(
        db.Integer, default=3, nullable=False, server_default='3',
    )
    # Результат останнього прогону синхронізації -- для сторінки інтеграції.
    sintegrum_last_sync_at = db.Column(db.DateTime(timezone=True))
    sintegrum_last_sync_status = db.Column(db.String(20), default='', server_default='')
    sintegrum_last_sync_error = db.Column(db.Text, default='', server_default='')

    # Затримка листа "Реєстрацію підтверджено" для НЕОПЛАЧЕНИХ реєстрацій.
    # Хто платить одразу (підтверджує в застосунку банку), встигав отримати
    # лист "до оплати" ще під час платежу. Пауза дає платежу дійти: якщо за
    # цей час прийшла оплата, лист не надсилається взагалі -- людина
    # отримує тільки "Ви в списку учасників". 0 -- слати негайно.
    registration_email_delay_minutes = db.Column(
        db.Integer, default=5, nullable=False, server_default='5',
    )

    # === Meta Lead Ads (ліди з інстант-форм Facebook/Instagram) ===
    #
    # App Secret і Page Access Token -- секрети з доступом до персональних
    # даних чужих людей, тож Fernet, як liqpay_private_key. Verify token --
    # теж секрет: знаючи його, сторонній може підписатись на наш ендпоінт
    # верифікації і дізнатись, що інтеграція існує.
    #
    # Page token навмисно БЕЗСТРОКОВИЙ (обміняний через довгоживучий User
    # token). Зберігати його в env означало б ручний деплой при кожній
    # ротації і рестарт застосунку -- критерій приймання N8 вимагає
    # протилежного: токен переживає перезапуск і не потребує втручання.
    meta_leads_enabled = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.false(),
    )
    meta_app_id = db.Column(db.String(50), default='', server_default='', nullable=False)
    _meta_app_secret_encrypted = db.Column(
        'meta_app_secret', db.String(500), default='', server_default='',
    )
    meta_app_secret_set_at = db.Column(db.DateTime(timezone=True))
    _meta_verify_token_encrypted = db.Column(
        'meta_verify_token', db.String(500), default='', server_default='',
    )
    _meta_page_token_encrypted = db.Column(
        'meta_page_token', db.String(2000), default='', server_default='',
    )
    meta_page_token_set_at = db.Column(db.DateTime(timezone=True))
    meta_page_id = db.Column(db.String(64), default='', server_default='', nullable=False)
    meta_page_name = db.Column(db.String(255), default='', server_default='', nullable=False)
    # Версія Graph API у шляху запитів. У налаштуваннях, а не в константі:
    # Meta виводить версії з ужитку за розкладом, і підняти її має бути
    # можна без релізу.
    meta_graph_version = db.Column(
        db.String(10), default='v21.0', server_default='v21.0', nullable=False,
    )

    # Звірка: як часто добирати ліди з Meta і за який період назад. 48 годин
    # -- запас на вихідні: збій у п'ятницю ввечері помічають у понеділок, а
    # Meta тримає ліди лише 90 днів.
    meta_reconcile_interval_minutes = db.Column(
        db.Integer, default=30, nullable=False, server_default='30',
    )
    meta_reconcile_lookback_hours = db.Column(
        db.Integer, default=48, nullable=False, server_default='48',
    )

    # Скільки годин тиші при активних формах вважати збоєм. 0 -- не сповіщати.
    meta_silence_alert_hours = db.Column(
        db.Integer, default=24, nullable=False, server_default='24',
    )
    # Скільки помилок у черзі накопичити, перш ніж написати менеджерам.
    meta_error_alert_threshold = db.Column(
        db.Integer, default=5, nullable=False, server_default='5',
    )

    # Режим тестування. Graph API не віддає надійного прапорця «це тест»:
    # заявки з Lead Ads Testing Tool приходять тим самим шляхом і виглядають
    # як справжні. Тому позначку ставимо самі й детерміновано -- усе, що
    # прийшло при увімкненому перемикачі, лягає з MetaLead.is_test=True.
    # Час увімкнення зберігаємо окремо: без нього неможливо відповісти, чи
    # був режим активний на момент конкретної заявки, коли його вже вимкнули.
    meta_test_mode = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.false(),
    )
    meta_test_mode_since = db.Column(db.DateTime(timezone=True))

    # Стан інтеграції для сторінки налаштувань і моніторингу.
    meta_last_lead_at = db.Column(db.DateTime(timezone=True))
    meta_last_webhook_at = db.Column(db.DateTime(timezone=True))
    meta_last_reconcile_at = db.Column(db.DateTime(timezone=True))
    meta_last_reconcile_status = db.Column(db.String(20), default='', server_default='')
    meta_last_reconcile_error = db.Column(db.Text, default='', server_default='')
    meta_token_checked_at = db.Column(db.DateTime(timezone=True))
    meta_token_valid = db.Column(db.Boolean)
    # NULL = безстроковий (Meta віддає expires_at=0 для page token).
    meta_token_expires_at = db.Column(db.DateTime(timezone=True))
    meta_token_error = db.Column(db.Text, default='', server_default='')
    # Коли востаннє слали алерт -- щоб не писати менеджерам щогодини про
    # ту саму тишу.
    meta_alert_sent_at = db.Column(db.DateTime(timezone=True))

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
    def sintegrum_api_key(self):
        if not self._sintegrum_api_key_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(
                self._sintegrum_api_key_encrypted.encode()
            ).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt sintegrum_api_key')
            return ''

    @sintegrum_api_key.setter
    def sintegrum_api_key(self, value):
        if not value:
            self._sintegrum_api_key_encrypted = ''
            return
        self._sintegrum_api_key_encrypted = _get_fernet().encrypt(value.encode()).decode()

    @property
    def sintegrum_api_key_is_set(self):
        """Чи заданий ключ. Для шаблонів -- щоб не тягнути в них сам секрет."""
        return bool(self._sintegrum_api_key_encrypted)

    @property
    def perf_api_key(self):
        if not self._perf_api_key_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(self._perf_api_key_encrypted.encode()).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt perf_api_key')
            return ''

    @perf_api_key.setter
    def perf_api_key(self, value):
        if not value:
            self._perf_api_key_encrypted = ''
            return
        self._perf_api_key_encrypted = _get_fernet().encrypt(value.encode()).decode()

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

    @property
    def effective_meta_pixel_id(self):
        """Meta Pixel ID -- БД, інакше env-fallback. Порожній рядок => Pixel
        не вмикається.

        Дзеркалить логіку reCAPTCHA, а не GA: прапорець enabled живе поруч з
        ID, тож джерело обираємо цілою парою. Якщо ID заданий у БД -- саме
        його прапорець і вирішує; env у цьому разі не підмінює вимкнення
        (інакше "вимкнув у адмінці, а воно й далі шле" -- пастка).
        """
        if self.meta_pixel_id:
            return self.meta_pixel_id if self.meta_pixel_enabled else ''
        env_id = current_app.config.get('META_PIXEL_ID', '') or ''
        if env_id and current_app.config.get('META_PIXEL_ENABLED', False):
            return env_id
        return ''

    @staticmethod
    def is_valid_meta_pixel_id(value):
        """Meta Pixel ID -- 15-16 цифр. Порожній рядок валідний (вимкнення)."""
        if not value:
            return True
        return bool(META_PIXEL_ID_RE.match(value))

    @staticmethod
    def _resolve_posthog_flag(db_value, config_key):
        """Тристанний прапорець: значення з БД, а NULL => env.

        Ключова властивість -- прапорець БД перекриває env В ОБИДВА БОКИ,
        незалежно від того, звідки взявся сам ключ. Попередня версія
        дивилась на наявність ключа в БД і через це мовчки ігнорувала
        вимкнення на проді, де ключ приходить з env.
        """
        if db_value is not None:
            return bool(db_value)
        return bool(current_app.config.get(config_key, False))

    @property
    def posthog_is_enabled(self):
        """Чи ввімкнена аналітика взагалі (без огляду на наявність ключа)."""
        return self._resolve_posthog_flag(self.posthog_enabled, 'POSTHOG_ENABLED')

    @property
    def effective_posthog_api_key(self):
        """PostHog Project API Key або '' якщо трекінгу немає.

        Прапорець і ключ розв'язуються НЕЗАЛЕЖНО: прапорець вирішує, чи
        збираємо взагалі, ключ -- куди слати. Саме тому вимкнення в адмінці
        діє й тоді, коли ключ лежить в env.
        """
        if not self.posthog_is_enabled:
            return ''
        return (
            self.posthog_project_api_key
            or current_app.config.get('POSTHOG_PROJECT_API_KEY', '')
            or ''
        )

    @property
    def effective_posthog_session_recording(self):
        """Чи писати сесії. Має сенс лише коли сам PostHog активний."""
        if not self.effective_posthog_api_key:
            return False
        return self._resolve_posthog_flag(
            self.posthog_session_recording, 'POSTHOG_SESSION_RECORDING')

    @property
    def effective_posthog_exclude_admin(self):
        """Чи прибрати адмінку з-під збору цілком.

        Окремо від iprm_section: та властивість дає фільтр у звітах, але
        події все одно доходять і витрачають квоту.
        """
        return self._resolve_posthog_flag(
            self.posthog_exclude_admin, 'POSTHOG_EXCLUDE_ADMIN')

    @staticmethod
    def is_valid_posthog_key(value):
        """Project API Key -- 'phc_' + хвіст. Порожній рядок валідний
        (вимкнення).

        Хвіст допускає '-' і '_': алфавіт токена PostHog ніде не
        зафіксований як строго алфавітно-цифровий, а зайва строгість тут
        відхиляла б валідний ключ із незрозумілою для адміна помилкою.
        """
        if not value:
            return True
        return bool(POSTHOG_KEY_RE.match(value))

    @property
    def meta_app_secret(self):
        if not self._meta_app_secret_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(
                self._meta_app_secret_encrypted.encode()
            ).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt meta_app_secret')
            return ''

    @meta_app_secret.setter
    def meta_app_secret(self, value):
        if not value:
            self._meta_app_secret_encrypted = ''
            return
        self._meta_app_secret_encrypted = _get_fernet().encrypt(value.encode()).decode()

    @property
    def meta_app_secret_is_set(self):
        return bool(self._meta_app_secret_encrypted)

    @property
    def meta_verify_token(self):
        if not self._meta_verify_token_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(
                self._meta_verify_token_encrypted.encode()
            ).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt meta_verify_token')
            return ''

    @meta_verify_token.setter
    def meta_verify_token(self, value):
        if not value:
            self._meta_verify_token_encrypted = ''
            return
        self._meta_verify_token_encrypted = _get_fernet().encrypt(value.encode()).decode()

    @property
    def meta_verify_token_is_set(self):
        return bool(self._meta_verify_token_encrypted)

    @property
    def meta_page_token(self):
        if not self._meta_page_token_encrypted:
            return ''
        try:
            return _get_fernet().decrypt(
                self._meta_page_token_encrypted.encode()
            ).decode()
        except (InvalidToken, Exception):
            logger.warning('Failed to decrypt meta_page_token')
            return ''

    @meta_page_token.setter
    def meta_page_token(self, value):
        if not value:
            self._meta_page_token_encrypted = ''
            return
        self._meta_page_token_encrypted = _get_fernet().encrypt(value.encode()).decode()

    @property
    def meta_page_token_is_set(self):
        return bool(self._meta_page_token_encrypted)

    @property
    def is_meta_leads_configured(self):
        """Чи вистачає налаштувань, щоб приймати й забирати ліди.

        Verify token у перевірку НЕ входить: він потрібен один раз, при
        підписці, і після неї його можна прибрати -- вебхук від цього не
        перестане працювати, бо POST-и підписані App Secret.
        """
        return bool(
            self.meta_app_id
            and self._meta_app_secret_encrypted
            and self._meta_page_token_encrypted
            and self.meta_page_id
        )

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
