"""
Email sending service with threaded delivery, retry logic, and audit logging.

Protection system:
- Stale pending cleanup: emails stuck >5 min in "pending" are marked failed.
- Retry with backoff: transient SMTP failures retried up to 3 times.
  Retry re-sends the saved html_body, not re-renders the template.
- Permanent failure detection: auth errors, bad addresses are never retried.
- Deduplication: same trigger+registration within 60s window is skipped.
- Circuit breaker: if >5 failures in last 10 min, new sends are paused.
- Test emails are always synchronous and never retried.
- Thread-safe: SMTP config is passed as a dict, never mutated on app.config.
"""
import html as _htmllib
import logging
import re
import smtplib
from datetime import datetime, timedelta, timezone
from threading import Thread

from flask import current_app, render_template
from flask_babel import force_locale, gettext as _
from flask_mail import Message

from app.extensions import db
from app.models.email_log import EmailLog, MAX_RETRIES, STALE_PENDING_MINUTES

logger = logging.getLogger(__name__)

_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)
_HEAD_RE = re.compile(r'<head\b[^>]*>.*?</head>', re.IGNORECASE | re.DOTALL)
_STYLE_SCRIPT_RE = re.compile(r'<(style|script)\b[^>]*>.*?</\1>', re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_BR_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)
_BLOCK_RE = re.compile(r'</?(?:p|div|tr|h[1-6]|li|ul|ol|table|td)\b[^>]*>', re.IGNORECASE)
_HTML_TAG_RE = re.compile(r'<[^>]+>')
# Невидимі символи: м'який перенос, CGJ, zero-width, figure/narrow space, BOM
# (ними напхано прихований preview-блок у base.html -- у тексті це сміття).
_INVISIBLE_RE = re.compile('[' + ''.join(map(chr, (0x00ad, 0x034f, 0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x2007, 0x202f, 0xfeff))) + ']')
_INLINE_WS_RE = re.compile('[ ' + chr(9) + chr(13) + chr(12) + chr(0xa0) + ']+')

DEDUP_WINDOW_SECONDS = 60

# utm_source для посилань, які ведуть з листів назад на сайт.
EMAIL_UTM_SOURCE = 'email'

CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_WINDOW_MINUTES = 10

# Timeout (seconds) for synchronous SMTP operations (test email).
SMTP_TIMEOUT_SECONDS = 15

# Мова листів за замовчуванням (вихідна мова проєкту). Адмінські
# нотифікації та листи без користувача-отримувача завжди йдуть нею.
DEFAULT_EMAIL_LOCALE = 'uk'


def _html_to_plaintext(html):
    """HTML -> текстова версія листа (plain-text alternative).

    Прибирає head/style/script/коментарі, зберігає URL посилань як "текст (url)",
    декодує HTML-entity і вирізає невидимі preview-символи з base.html. Завдяки
    цьому текстова частина близька до видимого HTML і не тригерить
    SpamAssassin MPART_ALT_DIFF_COUNT (через що листи летіли у спам).
    """
    text = _COMMENT_RE.sub('', html)
    text = _HEAD_RE.sub('', text)
    text = _STYLE_SCRIPT_RE.sub('', text)
    text = _LINK_RE.sub(lambda m: '{} ({})'.format(m.group(2), m.group(1)), text)
    text = _BR_RE.sub('\n', text)
    text = _BLOCK_RE.sub('\n', text)
    text = _HTML_TAG_RE.sub('', text)
    text = _htmllib.unescape(text)
    text = _INVISIBLE_RE.sub('', text)
    text = _INLINE_WS_RE.sub(' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _get_smtp_config(app):
    """Read SMTP settings from DB and return as an isolated dict (thread-safe)."""
    from app.models.email_settings import EmailSettings
    settings = EmailSettings.get()
    config = {
        'server': settings.smtp_server,
        'port': settings.smtp_port,
        'use_ssl': settings.smtp_use_ssl,
        'use_tls': settings.smtp_use_tls,
        'username': settings.smtp_username,
        'password': settings.smtp_password,
        'is_enabled': settings.is_enabled,
        'has_password': settings.has_password,
    }
    if settings.sender_name and settings.default_sender:
        config['sender'] = (settings.sender_name, settings.default_sender)
    elif settings.default_sender:
        config['sender'] = settings.default_sender
    else:
        config['sender'] = settings.smtp_username
    return config


def _smtp_send(msg, smtp_cfg):
    """Send a flask_mail.Message using the given SMTP config dict.

    This avoids mutating app.config, making it safe to call from any thread.
    """
    host_cls = smtplib.SMTP_SSL if smtp_cfg['use_ssl'] else smtplib.SMTP
    with host_cls(smtp_cfg['server'], smtp_cfg['port'], timeout=SMTP_TIMEOUT_SECONDS) as host:
        host.ehlo()
        if smtp_cfg['use_tls'] and not smtp_cfg['use_ssl']:
            host.starttls()
            host.ehlo()
        if smtp_cfg['username'] and smtp_cfg['password']:
            host.login(smtp_cfg['username'], smtp_cfg['password'])
        host.sendmail(smtp_cfg['username'], msg.send_to, msg.as_bytes())


def _sender_address(sender):
    """Витягти чисту email-адресу з sender (рядок або (name, addr))."""
    if isinstance(sender, (tuple, list)):
        return sender[1] if len(sender) > 1 else sender[0]
    return sender


def _open_smtp(smtp_cfg):
    """Відкрити автентифіковане SMTP-з'єднання за конфігом."""
    host_cls = smtplib.SMTP_SSL if smtp_cfg['use_ssl'] else smtplib.SMTP
    host = host_cls(smtp_cfg['server'], smtp_cfg['port'], timeout=SMTP_TIMEOUT_SECONDS)
    host.ehlo()
    if smtp_cfg['use_tls'] and not smtp_cfg['use_ssl']:
        host.starttls()
        host.ehlo()
    if smtp_cfg['username'] and smtp_cfg['password']:
        host.login(smtp_cfg['username'], smtp_cfg['password'])
    return host


def _smtp_send_many(messages, smtp_cfg):
    """Надіслати кілька повідомлень ОДНИМ SMTP-з'єднанням (ретраї/розсилки).

    Повертає list[(msg, error|None)] у тому ж порядку; помилка окремого листа
    не валить решту. Якщо не вдалось навіть відкрити з'єднання -- raise (caller
    лишає всі листи failed до наступного циклу)."""
    results = []
    with _open_smtp(smtp_cfg) as host:
        for msg in messages:
            try:
                host.sendmail(smtp_cfg['username'], msg.send_to, msg.as_bytes())
                results.append((msg, None))
            except Exception as exc:  # noqa: BLE001 -- ізолюємо збій одного листа
                results.append((msg, exc))
    return results


class EmailService:

    @staticmethod
    def _check_circuit_breaker():
        """Return True if too many recent failures (circuit open)."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=CIRCUIT_BREAKER_WINDOW_MINUTES)
        recent_failures = EmailLog.query.filter(
            EmailLog.status == 'failed',
            EmailLog.created_at >= cutoff,
            EmailLog.trigger != 'test',
        ).count()
        return recent_failures >= CIRCUIT_BREAKER_THRESHOLD

    @staticmethod
    def _check_duplicate(to, trigger, registration_id):
        """Return True if a duplicate email was sent/queued recently."""
        if not trigger or trigger == 'test':
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=DEDUP_WINDOW_SECONDS)
        query = EmailLog.query.filter(
            EmailLog.to_email == to,
            EmailLog.trigger == trigger,
            EmailLog.created_at >= cutoff,
            EmailLog.status.in_(['pending', 'sent']),
        )
        if registration_id:
            query = query.filter(EmailLog.registration_id == registration_id)
        return query.first() is not None

    @staticmethod
    def _safe_trigger(trigger, template_name=None):
        """Не дати невідомому trigger зронити INSERT email_logs (CHECK
        ck_email_logs_trigger). Поза ALLOWED -> warning + None (NULL не
        порушує CHECK), щоб лист усе одно пішов, а не загубився тихо."""
        if trigger is None or EmailLog.is_valid_trigger(trigger):
            return trigger
        logger.warning(
            'Unknown email trigger %r (template=%s): немає в EmailLog.TRIGGERS, '
            'зберігаю NULL. Додайте у TRIGGERS + міграцію CHECK.',
            trigger, template_name,
        )
        return None

    @staticmethod
    def _is_blocked(to, trigger):
        """True, якщо слати не можна: hard-bounce/скарга (будь-що) або
        відписка/opt-out для НЕОБОВ'ЯЗКОВИХ листів. 'test' не блокуємо."""
        if trigger == 'test':
            return False
        from app.models.email_suppression import EmailSuppression
        from app.models.user import User
        sup = EmailSuppression.get(to)
        if sup is not None:
            if sup.reason in (EmailSuppression.REASON_BOUNCE,
                              EmailSuppression.REASON_COMPLAINT):
                return True
            if EmailLog.is_optional_trigger(trigger):
                return True  # unsubscribe -> блокує лише необов'язкові
        if EmailLog.is_optional_trigger(trigger):
            user = User.query.filter_by(email=(to or '').strip().lower()).first()
            if user is not None and user.email_opt_out:
                return True
        return False

    @staticmethod
    def _idempotency_seen(key):
        return EmailLog.query.filter(
            EmailLog.idempotency_key == key,
            EmailLog.status.in_(['pending', 'sent']),
        ).first() is not None

    @staticmethod
    def _deliverability_headers(to, ctx, sender_addr):
        """List-Unsubscribe (+ one-click) для кращої доставки. Якщо адресат --
        зареєстрований User, додаємо https one-click із його токеном."""
        from app.models.user import User
        targets = []
        if sender_addr:
            targets.append(f'<mailto:{sender_addr}?subject=unsubscribe>')
        headers = {}
        site = ctx.get('site_settings')
        base = (getattr(site, 'website_url', '') or '').rstrip('/')
        user = User.query.filter_by(email=(to or '').strip().lower()).first()
        if user is not None and base:
            token = user.get_unsubscribe_token()
            targets.append(f'<{base}/unsubscribe/{token}>')
            headers['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'
        if targets:
            headers['List-Unsubscribe'] = ', '.join(targets)
        return headers

    @staticmethod
    def _recipient_locale(context, lang=None):
        """Мова рендеру листа: явний lang -> preferred_language
        користувача-отримувача (context['user']) -> DEFAULT_EMAIL_LOCALE.

        Централізує вибір локалі для force_locale: convenience-сендери
        кладуть отримувача у context['user'], тож окремо передавати мову
        не потрібно; адмінські нотифікації без 'user' лишаються 'uk'."""
        if lang:
            return lang
        user = (context or {}).get('user')
        return getattr(user, 'preferred_language', None) or DEFAULT_EMAIL_LOCALE

    @staticmethod
    def send_email(to, subject, template_name, context=None,
                   trigger=None, registration_id=None, attachments=None,
                   idempotency_key=None, lang=None):
        """
        Render email template and send via SMTP in background thread.

        Guards: disabled check, deduplication, circuit breaker.
        attachments -- optional list of (filename, mimetype, data_bytes) tuples,
        attached to the message before sending (e.g. certificate PDF).
        lang -- явна мова листа ('uk'/'ru'/'en'); якщо не задано, береться
        preferred_language отримувача з context['user'] (див. _recipient_locale).
        subject -- рядок АБО callable без аргументів. Callable викликається в
        локалі отримувача, тож тема перекладається так само, як тіло; рядок
        береться як є (адмінські й тестові листи лишаються українськими).
        Returns EmailLog instance (status may still be 'pending' if async).
        Returns None if dedup skipped.
        """
        app = current_app._get_current_object()
        ctx = dict(context or {})
        locale = EmailService._recipient_locale(ctx, lang)
        # Тему рахуємо в тій самій локалі, що й тіло. Раніше вона була готовим
        # f-рядком українською: російськомовний учасник бачив у списку пошти
        # українську тему і російський лист.
        if callable(subject):
            with force_locale(locale):
                subject = subject()
        # Email-шаблони використовують site_settings (website_url, socials,
        # copy). У request-flow це заповнює @app.before_request через g;
        # у background/scheduler контексті g.site_settings немає, тому
        # ін'єктимо явно, якщо caller не передав.
        if 'site_settings' not in ctx:
            from app.models.site_settings import SiteSettings
            ctx['site_settings'] = SiteSettings.get()

        # Невідомий trigger не має валити INSERT (CHECK) і губити лист.
        trigger = EmailService._safe_trigger(trigger, template_name)

        # Suppression (bounce/скарга -> блок усього; unsubscribe/opt-out ->
        # блок необов'язкових). Робимо рано -- до рендера й SMTP.
        if EmailService._is_blocked(to, trigger):
            logger.info('Suppressed/opted-out: skipping %s -> %s (trigger=%s)',
                        template_name, to, trigger)
            return None

        with app.app_context():
            smtp_cfg = _get_smtp_config(app)

        if not smtp_cfg['is_enabled']:
            logger.info('Email disabled, skipping: %s -> %s', template_name, to)
            log_entry = EmailLog(
                to_email=to,
                subject=subject,
                template_name=template_name,
                status='failed',
                error_message='Email sending is disabled in settings',
                trigger=trigger,
                registration_id=registration_id,
            )
            db.session.add(log_entry)
            db.session.commit()
            return log_entry

        if EmailService._check_duplicate(to, trigger, registration_id):
            logger.info('Dedup: skipping %s -> %s (trigger=%s reg=%s)',
                        template_name, to, trigger, registration_id)
            return None

        if idempotency_key and EmailService._idempotency_seen(idempotency_key):
            logger.info('Idempotent skip: %s -> %s (key=%s)',
                        template_name, to, idempotency_key)
            return None

        if EmailService._check_circuit_breaker():
            logger.warning('Circuit breaker OPEN: skipping %s -> %s', template_name, to)
            log_entry = EmailLog(
                to_email=to,
                subject=subject,
                template_name=template_name,
                status='failed',
                error_message='Circuit breaker: too many recent failures, sending paused',
                trigger=trigger,
                registration_id=registration_id,
            )
            db.session.add(log_entry)
            db.session.commit()
            return log_entry

        try:
            # Рендер мовою отримувача: поза HTTP-запитом (scheduler, фонові
            # джоби) get_locale() повертає дефолт, тому локаль форсуємо явно.
            with force_locale(locale):
                html_body = render_template(f'emails/{template_name}.html', **ctx)
        except Exception as exc:
            log_entry = EmailLog(
                to_email=to,
                subject=subject,
                template_name=template_name,
                status='failed',
                error_message=f'Template render error: {str(exc)[:400]}',
                trigger=trigger,
                registration_id=registration_id,
            )
            db.session.add(log_entry)
            db.session.commit()
            logger.exception('Failed to render email template %s', template_name)
            return log_entry

        # Заголовки доставлюваності рахуємо ДО commit -- _deliverability_headers
        # лениво генерує user.unsubscribe_token (flush), і він має закомітитись
        # разом із логом.
        sender_addr = _sender_address(smtp_cfg['sender'])
        extra_headers = EmailService._deliverability_headers(to, ctx, sender_addr)

        log_entry = EmailLog(
            to_email=to,
            subject=subject,
            template_name=template_name,
            status='pending',
            trigger=trigger,
            registration_id=registration_id,
            html_body=html_body,
            idempotency_key=idempotency_key,
        )
        db.session.add(log_entry)
        db.session.commit()

        plain_body = _html_to_plaintext(html_body)
        msg = Message(
            subject=subject,
            recipients=[to],
            html=html_body,
            body=plain_body,
            sender=smtp_cfg['sender'],
            reply_to=sender_addr,
            extra_headers=extra_headers,
        )

        for attachment in (attachments or []):
            filename, mimetype, data = attachment
            msg.attach(filename, mimetype, data)

        thread = Thread(
            target=EmailService._send_in_thread,
            args=(app, msg, log_entry.id, smtp_cfg),
        )
        thread.daemon = True
        thread.start()

        return log_entry

    @staticmethod
    def _send_in_thread(app, msg, log_id, smtp_cfg):
        """Execute SMTP send in background thread with isolated config."""
        with app.app_context():
            log_entry = db.session.get(EmailLog, log_id)
            if not log_entry:
                logger.error('EmailLog %s not found in thread', log_id)
                return
            try:
                _smtp_send(msg, smtp_cfg)
                log_entry.status = 'sent'
                log_entry.sent_at = datetime.now(timezone.utc)
                logger.info('Email sent to %s: %s', msg.recipients[0], msg.subject)
            except Exception as exc:
                log_entry.status = 'failed'
                log_entry.error_message = str(exc)[:500]
                logger.exception('Failed to send email to %s', msg.recipients[0])
            finally:
                db.session.commit()

            # Партнер веде картку тієї самої людини. Без цього рядка менеджер
            # MM Medic дзвонить із пропозицією рівно тоді, коли ми написали їй
            # утретє за тиждень, — і бачить у картці порожнечу.
            #
            # ПІСЛЯ коміту й поза try: збій постановки в чергу не має
            # перетворювати надісланий лист на «не надісланий».
            try:
                from app.services.partner_events import emit_communication_sent
                emit_communication_sent(log_entry)
            except Exception:
                logger.exception('Partner communication event failed for log %s',
                                 log_id)

    # ---- Convenience senders ----

    @staticmethod
    def _site_base_url():
        """Канонічна база сайту без хвостового слеша."""
        from app.models.site_settings import SiteSettings
        return (SiteSettings.get().website_url or '').rstrip('/')

    @staticmethod
    def _with_utm(url, campaign, content=None):
        """Розмітити внутрішнє посилання з листа utm-мітками.

        Без цього клік із листа зливається в GA4 з прямими заходами, і
        зрозуміти, чи листи взагалі повертають людей на сайт, неможливо.
        Наявні параметри зберігаються, utm_* перезаписуються.
        """
        if not url:
            return url
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
        parts = urlparse(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query['utm_source'] = EMAIL_UTM_SOURCE
        query['utm_medium'] = 'email'
        query['utm_campaign'] = campaign
        if content:
            query['utm_content'] = content
        return urlunparse(parts._replace(query=urlencode(query)))

    @staticmethod
    def _event_from_registration(registration):
        """Шаблони очікують об'єкт `event` з полями title/start_date/location/...

        Адаптуємо CourseInstance + Course до цієї форми без змін шаблонів.
        """
        instance = registration.instance
        if instance is None or instance.course is None:
            return None
        course = instance.course

        class _EventShape:
            slug = course.slug
            start_date = instance.start_date
            end_date = instance.end_date
            location = instance.location
            online_link = instance.online_link
            event_format = instance.event_format
            price = instance.effective_price
            cpd_points = instance.effective_cpd_points

            # Властивості, а не готові значення: читаються під час рендеру,
            # тобто вже всередині force_locale. Раніше тут лежала канонічна
            # українська назва, і російськомовний отримувач бачив її і в темі,
            # і в тілі листа, хоч решта листа була його мовою.
            @property
            def title(self):
                return course.t('title')

            @property
            def subtitle(self):
                return course.t('subtitle')

        return _EventShape()

    @staticmethod
    def send_registration_confirmation(registration):
        event = EmailService._event_from_registration(registration)
        if event is None:
            logger.warning(
                'Cannot send registration_confirmed: reg=%s has no instance/course',
                registration.id,
            )
            return None
        user = registration.user
        # Нагадування про МОЗ-анкету: показуємо блок у листі, поки профіль
        # неповний (анкета -- умова сертифіката, збирається в кабінеті).
        profile = user.medical_profile
        from app.models.site_settings import SiteSettings
        base = (SiteSettings.get().website_url or '').rstrip('/')
        certdata_url = f'{base}/auth/account/certificate-data'
        result = EmailService.send_email(
            to=user.email,
            subject=lambda: _('Реєстрацію підтверджено: %(title)s', title=event.title),
            template_name='registration_confirmed',
            context={
                'user': user, 'event': event, 'registration': registration,
                'pay_url': EmailService._pay_url_for_registration(registration),
                # Гість ще не має входу: анкета для сертифіката йому
                # недоступна, тож замість неї пропонуємо завести кабінет
                # (посилання те саме, що й на оплату -- там форма пароля).
                'needs_account': not user.has_password,
                'certdata_needed': (user.has_password
                                    and not (profile and profile.is_complete)),
                'certdata_url': certdata_url,
            },
            trigger='registration',
            registration_id=registration.id,
        )
        EmailService.notify_admins_event(
            event_type='registration',
            registration=registration,
            event=event,
            kind_label='Нова реєстрація на захід',
        )
        return result

    @staticmethod
    def send_completion_link(registration, complete_url):
        """Надіслати учаснику посилання на самостійне завершення анкети та
        вибір способу оплати (token-флоу). Викликається лише для учасників із
        реальним email (placeholder-адреси відсіює caller).

        trigger='registration' (а не окремий 'completion_link') свідомо: це
        частина воронки реєстрації, і так уникаємо зміни CHECK-констрейнта
        email_logs.trigger.
        """
        event = EmailService._event_from_registration(registration)
        if event is None:
            logger.warning(
                'Cannot send completion_link: reg=%s has no instance/course',
                registration.id,
            )
            return None
        user = registration.user
        return EmailService.send_email(
            to=user.email,
            subject=lambda: _('Завершіть реєстрацію: %(title)s', title=event.title),
            template_name='completion_link',
            context={
                'user': user, 'event': event, 'registration': registration,
                'complete_url': complete_url,
            },
            trigger='registration',
            registration_id=registration.id,
        )

    @staticmethod
    def send_email_confirmation(user, confirm_url):
        return EmailService.send_email(
            to=user.email,
            subject=lambda: _('Підтвердіть ваш email | ІПРМ'),
            template_name='email_confirm',
            context={'user': user, 'confirm_url': confirm_url},
            trigger='email_confirm',
        )

    @staticmethod
    def send_password_reset(user, reset_url):
        return EmailService.send_email(
            to=user.email,
            subject=lambda: _('Відновлення паролю | ІПРМ'),
            template_name='password_reset',
            context={'user': user, 'reset_url': reset_url},
            trigger='password_reset',
        )

    @staticmethod
    def _will_be_delivered(to, trigger):
        """Чи має сенс готувати вміст листа для цього адресата.

        Побічні ефекти (видача промокоду, генерація реферального коду)
        пишуть у БД ДО send_email, а той може мовчки нічого не надіслати.
        Без цієї перевірки кожна оплата при вимкненій розсилці або
        заблокованій адресі плодила б промокод, якого ніхто не отримає.

        Перевіряємо лише сталі умови; дедуп і circuit breaker -- тимчасові
        (і видача коду до них ідемпотентна), тож їх лишаємо send_email.
        """
        try:
            from app.models.email_settings import EmailSettings
            if not EmailSettings.get().is_enabled:
                return False
            return not EmailService._is_blocked(to, trigger)
        except Exception:
            logger.exception('Delivery pre-check failed for %s', to)
            return False

    @staticmethod
    def schedule_registration_confirmation(registration):
        """Поставити лист "Реєстрацію підтверджено" в чергу з паузою.

        Навіщо пауза: людина, яка платить одразу (підтверджує платіж у
        застосунку банку), встигала отримати лист "до оплати" ще ДО того,
        як платіж дійшов. Через N хвилин планувальник перевіряє статус
        повторно: якщо оплата вже є -- лист не піде взагалі, бо
        payment_confirmed каже все те саме й більше.

        Пауза має сенс лише там, де є гонка з онлайн-платежем:
          * безкоштовній участі чекати нічого (payment_status уже 'paid');
          * оплата за рахунком іде через банк, а цей лист -- інструкція,
            як завантажити рахунок; тримати її п'ять хвилин це чисте тертя.

        МУТУЄ сесію без commit -- caller відповідає за commit.
        Повертає True, якщо лист відкладено (тобто слати зараз НЕ треба).
        """
        from datetime import timedelta
        from app.models.mixins import utcnow
        from app.models.site_settings import SiteSettings

        if registration.payment_status == 'paid':
            return False
        if registration.payment_method == 'invoice':
            return False
        try:
            delay = int(SiteSettings.get().registration_email_delay_minutes or 0)
        except Exception:
            logger.exception('Cannot read registration email delay')
            return False
        if delay <= 0:
            return False

        registration.confirmation_email_due_at = utcnow() + timedelta(minutes=delay)
        logger.info('REG-%d: лист про реєстрацію відкладено на %d хв',
                    registration.id, delay)
        return True

    @staticmethod
    def cancel_pending_registration_confirmation(registration):
        """Скасувати відкладений лист (оплата прийшла раніше за таймер).

        МУТУЄ сесію без commit. Повертає True, якщо було що скасовувати.
        """
        if registration.confirmation_email_due_at is None:
            return False
        registration.confirmation_email_due_at = None
        logger.info('REG-%d: відкладений лист про реєстрацію скасовано '
                    '(оплата надійшла раніше)', registration.id)
        return True

    @staticmethod
    def send_due_registration_confirmations(limit=100):
        """Надіслати листи, чий час настав. Викликається планувальником.

        Мітку знімаємо ОДНИМ комітом ДО надсилання, а не після. Дві
        причини. По-перше, send_email відкриває власний app-context (а з
        ним і власну сесію), тож зміна, залишена "на потім", до бази не
        доїжджає. По-друге, якщо процес упаде посеред розсилки, мітка вже
        знята -- інакше наступний запуск надіслав би ті самі листи ще раз.

        Ціна -- лист може загубитись при падінні саме в цю мить. Для
        разового підтвердження це дешевше за дубль.
        """
        from app.models.mixins import utcnow
        from app.models.registration import EventRegistration

        due = (EventRegistration.query
               .filter(EventRegistration.confirmation_email_due_at.isnot(None),
                       EventRegistration.confirmation_email_due_at <= utcnow())
               .order_by(EventRegistration.confirmation_email_due_at.asc())
               .limit(limit).all())
        if not due:
            return 0, 0

        # Кого слати -- вирішуємо ДО зняття міток: після коміту об'єкти
        # можуть перечитатись, а рішення має спиратись на стан "на момент
        # настання часу".
        to_send = []
        skipped = 0
        for reg in due:
            if reg.payment_status == 'paid' or reg.status == 'cancelled':
                skipped += 1
                logger.info(
                    'REG-%d: лист про реєстрацію не потрібен (status=%s '
                    'payment=%s)', reg.id, reg.status, reg.payment_status,
                )
            else:
                to_send.append(reg)
            reg.confirmation_email_due_at = None
        db.session.commit()

        sent = 0
        for reg in to_send:
            try:
                EmailService.send_registration_confirmation(reg)
                sent += 1
            except Exception:
                logger.exception(
                    'Failed to send delayed confirmation for REG-%d', reg.id,
                )
        return sent, skipped

    @staticmethod
    def _thankyou_promo(registration):
        """Персональний код на наступний курс (або None). Комітить сам.

        Best-effort: збій видачі не має гасити лист про оплату, тому
        помилка ловиться тут, а не спливає в платіжний флоу.
        """
        if not getattr(registration, 'user_has_real_email', False):
            return None
        try:
            from app.services import promo_service
            promo = promo_service.issue_thankyou_code(registration)
            if promo is not None:
                db.session.commit()
            return promo
        except Exception:
            db.session.rollback()
            logger.exception(
                'Thank-you promo issue failed for reg=%s', registration.id,
            )
            return None

    @staticmethod
    def _referral_link_for(user):
        """Реферальне посилання учасника (або None, якщо програму вимкнено)."""
        try:
            from app.models.site_settings import SiteSettings
            if not SiteSettings.get().referral_enabled:
                return None
            from app.services import referral_service
            link = referral_service.user_referral_link(user)
            db.session.commit()  # ensure_referral_code робить лише flush
            return link
        except Exception:
            db.session.rollback()
            logger.exception('Referral link build failed for user=%s',
                             getattr(user, 'id', None))
            return None

    @staticmethod
    def send_payment_confirmation(registration):
        event = EmailService._event_from_registration(registration)
        if event is None:
            logger.warning(
                'Cannot send payment_confirmed: reg=%s has no instance/course',
                registration.id,
            )
            return None
        user = registration.user
        base = EmailService._site_base_url()
        will_send = EmailService._will_be_delivered(user.email, 'payment')

        # Лист про оплату -- пік довіри і водночас глухий кут: далі людині
        # нічого робити. Тому даємо три виходи назад на сайт: кабінет
        # (кнопка), календар (щоб не забула про курс) і причину повернутись
        # -- реферальне посилання та персональний код на наступний курс.
        #
        # Вкладення переживає лише перше надсилання: retry_failed_emails
        # пересилає збережений html_body без attachments, і .ics до
        # адресата не доїде. Деградація м'яка -- кнопка Google Calendar у
        # тілі листа лишається робочою.
        from app.services import calendar_service
        attachment = calendar_service.ics_attachment(
            event, registration=registration, base_url=base,
        )
        promo = EmailService._thankyou_promo(registration) if will_send else None

        # Гість після гостьового чекауту має акаунт, але не має пароля:
        # /auth/account зустріне його логіном, крізь який він не пройде.
        # Ведемо на ту саму token-сторінку, що й лист про реєстрацію.
        needs_account = not user.has_password
        entry_url = (EmailService._pay_url_for_registration(registration)
                     if needs_account
                     else (f'{base}/auth/account' if base else None))

        result = EmailService.send_email(
            to=user.email,
            subject=lambda: _('Ви в списку учасників: %(title)s', title=event.title),
            template_name='payment_confirmed',
            context={
                'user': user, 'event': event, 'registration': registration,
                'needs_account': needs_account,
                'account_url': EmailService._with_utm(
                    entry_url, 'payment_confirmed', 'account',
                ) if entry_url else None,
                'course_url': EmailService._with_utm(
                    f'{base}/courses/{event.slug}', 'payment_confirmed', 'course',
                ) if base and event.slug else None,
                'courses_url': EmailService._with_utm(
                    f'{base}/courses', 'payment_confirmed', 'catalog',
                ) if base else None,
                'gcal_url': calendar_service.google_calendar_url(
                    event, base_url=base,
                ),
                'has_ics': attachment is not None,
                'referral_link': (EmailService._referral_link_for(user)
                                  if will_send else None),
                'promo': promo,
            },
            trigger='payment',
            registration_id=registration.id,
            attachments=[attachment] if attachment else None,
        )
        EmailService.notify_admins_event(
            event_type='payment',
            registration=registration,
            event=event,
            kind_label='Підтверджена оплата',
        )
        return result

    @staticmethod
    def send_online_access(enrollment, access_url, promo=None):
        """Посилання на навчання після оплати онлайн-курсу.

        trigger='payment', а не окремий 'online_access': це продовження
        платіжної воронки, і так не доводиться правити CHECK
        ck_email_logs_trigger заради одного шаблону (той самий підхід, що
        в send_completion_link).

        registration_id не передаємо -- у замовлення онлайн-курсу немає
        реєстрації на захід; зв'язок з покупкою тримає сам enrollment.
        """
        user = enrollment.user
        course = enrollment.course
        if user is None or not user.email:
            logger.warning('Cannot send online_access: %s has no user email',
                           enrollment.order_id)
            return None

        base = EmailService._site_base_url()
        return EmailService.send_email(
            to=user.email,
            subject=lambda: _('Доступ до курсу: %(title)s',
                              title=course.effective_title),
            template_name='online_access',
            context={
                'user': user,
                'course': course,
                'enrollment': enrollment,
                'access_url': access_url,
                'account_url': f'{base}/auth/account' if base else None,
                'promo': promo,
            },
            trigger='payment',
        )

    @staticmethod
    def send_course_reminder(registration, days_until):
        event = EmailService._event_from_registration(registration)
        if event is None:
            logger.warning(
                'Cannot send course_reminder: reg=%s has no instance/course',
                registration.id,
            )
            return None
        user = registration.user
        return EmailService.send_email(
            to=user.email,
            subject=lambda: _('Нагадування: %(title)s через %(days)s дн.',
                             title=event.title, days=days_until),
            template_name='course_reminder',
            context={
                'user': user, 'event': event,
                'registration': registration, 'days_until': days_until,
            },
            trigger='reminder',
            registration_id=registration.id,
        )

    @staticmethod
    def send_status_change(registration, old_status, new_status):
        event = EmailService._event_from_registration(registration)
        if event is None:
            logger.warning(
                'Cannot send status_changed: reg=%s has no instance/course',
                registration.id,
            )
            return None
        user = registration.user
        label = dict(registration.STATUSES).get(new_status, new_status)
        result = EmailService.send_email(
            to=user.email,
            subject=lambda: _('Статус реєстрації змінено: %(title)s', title=event.title),
            template_name='status_changed',
            context={
                'user': user, 'event': event, 'registration': registration,
                'old_status': old_status, 'new_status': new_status,
                'new_status_label': label,
            },
            trigger='status_change',
            registration_id=registration.id,
        )
        # Admin-нотифікацію шлемо за фільтром rule.trigger_statuses
        # (за замовчуванням -- лише 'cancelled'). resolve() сам відсіє,
        # якщо new_status не в списку.
        EmailService.notify_admins_event(
            event_type='status_change',
            registration=registration,
            event=event,
            kind_label='Скасування реєстрації' if new_status == 'cancelled'
                else f'Зміна статусу: {label}',
            extra_context={'new_status_label': label},
            new_status=new_status,
        )
        return result

    @staticmethod
    def send_certificate(certificate):
        """Надіслати користувачу лист з PDF-сертифікатом у вкладенні."""
        from app.services.certificate_service import read_pdf_bytes

        user = certificate.user
        if user is None:
            logger.warning('Cannot send certificate %s: no user', certificate.id)
            return None

        try:
            pdf_bytes = read_pdf_bytes(certificate)
        except Exception:
            logger.exception('Failed to read/generate certificate PDF %s', certificate.id)
            return None

        filename = f'{certificate.number}.pdf'
        return EmailService.send_email(
            to=user.email,
            subject=lambda: _('Ваш сертифікат: %(title)s', title=certificate.event_title),
            template_name='certificate_issued',
            context={
                'user': user,
                'certificate': certificate,
                # Шлях будуємо ТУТ, як у решті листів. Шаблон раніше склеював
                # website_url ~ "/account" -- а такого маршруту не існує
                # (кабінет живе на /auth/account), тож кнопка в листі вела у
                # 404. Заодно rstrip знімає подвійний слеш, якщо в
                # налаштуваннях домен записали з кінцевим "/".
                'account_url': EmailService._account_url(),
            },
            trigger='certificate',
            registration_id=certificate.registration_id,
            attachments=[(filename, 'application/pdf', pdf_bytes)],
        )

    @staticmethod
    def _account_url():
        """Абсолютне посилання на особистий кабінет.

        Береться з SiteSettings.website_url, а не через url_for(_external=True):
        листи рендеряться і поза request-контекстом (фонові розсилки), де
        зовнішні URL збиралися б із SERVER_NAME, якого в конфізі немає.
        """
        from app.models.site_settings import SiteSettings

        base = (SiteSettings.get().website_url or '').rstrip('/')
        return f'{base}/auth/account' if base else '/auth/account'

    @staticmethod
    def send_course_request_notification(course_request):
        """Повідомити адмінів про новий CourseRequest (клієнт залишив запит).

        Делегує у notify_admins_with_template (course_request не має
        registration/instance/trainer-контексту, тож шлемо event-specific
        шаблон course_request_notification.html напряму).
        """
        from app.models.site_settings import SiteSettings
        settings = SiteSettings.get()
        base = (settings.website_url or '').rstrip('/')
        admin_url = (
            f'{base}/admin/course-requests/{course_request.id}/edit'
            if base else f'/admin/course-requests/{course_request.id}/edit'
        )
        course = course_request.course
        subject = (
            f'Новий запит на курс: '
            f'{course.title if course else course_request.course_id}'
        )
        return EmailService.notify_admins_with_template(
            event_type='course_request',
            subject=subject,
            template_name='course_request_notification',
            context={
                'request_obj': course_request,
                'course': course,
                'admin_url': admin_url,
            },
        )

    @staticmethod
    def send_referral_award(to_email, referrer_name, points, balance,
                            event_title=None, idempotency_key=None, lang=None):
        """Повідомити реферера про нарахування бонусних балів.

        Необов'язковий лист (trigger='referral' поважає opt-out/unsubscribe).
        Викликається best-effort з referral_service після успішного нарахування.
        lang -- мова листа (referral_service передає preferred_language
        реферера-користувача; для тренерів лишається 'uk').
        """
        if not to_email:
            return None
        from app.models.site_settings import SiteSettings
        base = (SiteSettings.get().website_url or '').rstrip('/')
        account_url = f'{base}/auth/account' if base else '/auth/account'
        return EmailService.send_email(
            to=to_email,
            subject=f'Вам нараховано +{points} бонусних балів',
            template_name='referral_award',
            context={
                'referrer_name': referrer_name,
                'points': points,
                'balance': balance,
                'event_title': event_title,
                'account_url': account_url,
            },
            trigger='referral',
            idempotency_key=idempotency_key,
            lang=lang,
        )

    @staticmethod
    def send_certdata_reminder(registration):
        """Нагадати учаснику заповнити МОЗ-анкету (дані для сертифіката).

        Викликається scheduler-джобою send_certdata_reminders за N днів до
        заходу (N -- SiteSettings.certdata_reminder_days), один раз на
        реєстрацію (certdata_reminder_sent_at). trigger='reminder' --
        наявний opt-out-able тригер, CHECK email_logs не чіпаємо.
        """
        event = EmailService._event_from_registration(registration)
        if event is None:
            logger.warning(
                'Cannot send certdata_reminder: reg=%s has no instance/course',
                registration.id,
            )
            return None
        from app.models.site_settings import SiteSettings
        base = (SiteSettings.get().website_url or '').rstrip('/')
        return EmailService.send_email(
            to=registration.user.email,
            subject=lambda: _('Заповніть дані для сертифіката: %(title)s', title=event.title),
            template_name='certdata_reminder',
            context={
                'user': registration.user,
                'event': event,
                'registration': registration,
                'certdata_url': f'{base}/auth/account/certificate-data',
            },
            trigger='reminder',
            registration_id=registration.id,
        )

    @staticmethod
    def send_b2b_request_notification(b2b_request):
        """Повідомити адмінів про нову B2B-заявку (корпоративне навчання).

        Перевикористовує event_type/тригер 'course_request' (той самий
        список отримувачів і дозволене значення CHECK у email_logs) --
        семантично це теж запит на навчання.
        """
        from app.models.site_settings import SiteSettings
        settings = SiteSettings.get()
        base = (settings.website_url or '').rstrip('/')
        admin_url = f'{base}/admin/b2b-requests' if base else '/admin/b2b-requests'
        return EmailService.notify_admins_with_template(
            event_type='course_request',
            subject=f'Нова B2B-заявка: {b2b_request.full_name} ({b2b_request.team_size_label} фахівців)',
            template_name='b2b_request_notification',
            context={
                'request_obj': b2b_request,
                'admin_url': admin_url,
            },
        )

    @staticmethod
    def notify_overbooking(registration, occupied, capacity):
        """Попередити адмінів, що оплачених місць стало більше за місткість.

        Перевикористовує event_type/тригер 'payment': подія народжується
        саме в момент оплати, адресати ті самі, і значення вже дозволене
        CHECK-ом email_logs.trigger (окремий тип події коштував би двох
        міграцій CHECK -- див. коментар у NotificationRule).
        """
        instance = registration.instance if registration is not None else None
        course = instance.course if instance is not None else None
        user = registration.user if registration is not None else None
        title = course.title if course is not None else 'Захід'
        return EmailService.notify_admins_with_template(
            event_type='payment',
            subject=f'Перевищення місць: {title} ({occupied}/{capacity})',
            template_name='overbooking_alert',
            context={
                'event_title': title,
                'event_date': (
                    instance.start_date.strftime('%d.%m.%Y')
                    if instance is not None and instance.start_date else None
                ),
                'occupied': occupied,
                'capacity': capacity,
                'overflow': occupied - capacity,
                'participant_name': (
                    user.full_name if user is not None and hasattr(user, 'full_name')
                    else (user.email if user is not None else '–')
                ),
                'registration_id': registration.id if registration is not None else None,
                'admin_url': EmailService._admin_url_for_registration(registration),
            },
            registration=registration,
        )

    @staticmethod
    def send_blog_comment_notification(comment):
        """Повідомити адміна про новий коментар у блозі (на модерації).

        Шлемо на контактний email сайту (SiteSettings.email). Best-effort:
        якщо пошту не налаштовано або email порожній -- тихо пропускаємо.
        """
        from app.models.site_settings import SiteSettings
        settings = SiteSettings.get()
        to = (settings.email or '').strip()
        if not to:
            return None
        base = (settings.website_url or '').rstrip('/')
        admin_url = f'{base}/admin/blog/comments' if base else '/admin/blog/comments'
        post = comment.post
        return EmailService.send_email(
            to=to,
            subject=f'Новий коментар у блозі: {post.title if post else ""}',
            template_name='blog_comment_notification',
            context={'comment': comment, 'post': post, 'admin_url': admin_url},
            trigger='blog_comment',
        )

    # ------------------------------------------------------------------
    # ADMIN NOTIFICATION HELPERS (Phase 2 refactor)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_admin_subject(event_type, event, user, registration=None):
        """Спільне правило формування subject для admin-нотифікації.

        Замість того, щоб кожен send_* конструював свій рядок (DRY),
        формат уніфіковано: '<префікс>: <event-title> -- <user>'.
        Префікс залежить від event_type, fallback -- 'Подія'.

        Для оплати префікс несе суму, а для безкоштовної реєстрації --
        помітку: адмін бачить у списку листів десятки однакових тем, і
        саме сума відрізняє платіж на 500 грн від платежу на 25 000.
        """
        prefixes = {
            'registration': 'Нова реєстрація',
            'payment': 'Оплата отримана',
            'status_change': 'Зміна статусу реєстрації',
        }
        prefix = prefixes.get(event_type, 'Подія')
        if registration is not None:
            amount = registration.payment_amount
            if event_type == 'payment' and amount and amount > 0:
                prefix = f'Оплата {int(amount)} UAH'
            elif event_type == 'registration' and registration.payment_status == 'paid':
                prefix = 'Нова реєстрація (безкоштовно)'
        title = event.title if event is not None else event_type
        who = (user.full_name if user is not None else None) or \
              (user.email if user is not None else 'unknown')
        return f'{prefix}: {title} – {who}'

    @staticmethod
    def _pay_url_for_registration(registration):
        """Публічний deep-link на сторінку підтвердження/оплати реєстрації
        (де доступні LiqPay і завантаження рахунка). Будується з website_url,
        бо лист може формуватись без request-контексту (планувальник).

        Для гостьової покупки веде на token-сторінку: /registration/<id>
        вимагає входу, і лист гостю впирався б у логін -- рівно той бар'єр,
        який гостьовий чекаут прибирає.
        """
        from app.models.site_settings import SiteSettings
        base = (SiteSettings.get().website_url or '').rstrip('/')
        if registration.completion_token_active:
            tail = f'/registration/complete/{registration.completion_token}/pay'
        else:
            tail = f'/registration/{registration.id}'
        return f'{base}{tail}' if base else tail

    @staticmethod
    def _admin_url_for_registration(registration):
        """Deep-link на сторінку реєстрацій конкретного instance, з
        fallback на загальний список -- якщо немає website_url або
        instance_id."""
        from app.models.site_settings import SiteSettings
        base = (SiteSettings.get().website_url or '').rstrip('/')
        if registration is not None and registration.instance_id is not None:
            tail = f'/admin/instances/{registration.instance_id}/registrations'
        else:
            tail = '/admin/registrations'
        return f'{base}{tail}' if base else tail

    @staticmethod
    def _send_to_recipients(recipients, *, subject, template_name,
                            context, trigger, registration_id):
        """Циклічно шле send_email кожному адресату з ізоляцією помилок.

        send_email самостійно ловить шаблонні помилки, але INSERT
        email_logs (CHECK / IntegrityError) і несподіванки залишають
        сесію у failed-state -- наступний send_email впав би
        PendingRollbackError. Огортаємо кожну ітерацію у try з
        rollback, щоб провал на одній адресі не блокував решту.
        """
        results = []
        for to in recipients:
            try:
                entry = EmailService.send_email(
                    to=to,
                    subject=subject,
                    template_name=template_name,
                    context=context,
                    trigger=trigger,
                    registration_id=registration_id,
                )
                results.append(entry)
            except Exception:
                db.session.rollback()
                logger.exception(
                    'notify_admins: send_email failed for to=%s trigger=%s',
                    to, trigger,
                )
                results.append(None)
        return results

    @staticmethod
    def notify_admins_event(event_type, registration=None, event=None,
                            kind_label=None, extra_context=None,
                            new_status=None):
        """Generic admin-нотифікація з шаблоном admin_event_notification.html.

        Використовується для registration / payment / status_change. Усе,
        що потрібно, тримається у registration (з якого витягуємо instance,
        user, instance_id). subject формується через _build_admin_subject.
        new_status передається у resolve() для status_change-фільтрації.
        """
        from app.services.notification_recipients import resolve

        instance = registration.instance if registration is not None else None
        recipients = resolve(event_type, instance=instance, new_status=new_status)
        if not recipients:
            return []

        user = registration.user if registration is not None else None
        subject = EmailService._build_admin_subject(
            event_type, event, user, registration=registration,
        )
        ctx = {
            'kind_label': kind_label or event_type,
            'registration': registration,
            'event': event,
            'admin_url': EmailService._admin_url_for_registration(registration),
        }
        if extra_context:
            ctx.update(extra_context)

        return EmailService._send_to_recipients(
            recipients,
            subject=subject,
            template_name='admin_event_notification',
            context=ctx,
            trigger=event_type,
            registration_id=registration.id if registration is not None else None,
        )

    @staticmethod
    def notify_admins_with_template(event_type, subject, template_name,
                                    context, registration=None,
                                    new_status=None):
        """Admin-нотифікація з event-specific шаблоном і власним subject.

        Використовується для course_request (з шаблоном
        course_request_notification.html, що передує цьому рефактору
        і має власний дизайн). Caller повністю контролює subject і
        context; ми лише резолвимо адресатів і шлемо.
        """
        from app.services.notification_recipients import resolve

        instance = registration.instance if registration is not None else None
        recipients = resolve(event_type, instance=instance, new_status=new_status)
        if not recipients:
            return []

        return EmailService._send_to_recipients(
            recipients,
            subject=subject,
            template_name=template_name,
            context=context,
            trigger=event_type,
            registration_id=registration.id if registration is not None else None,
        )

    # ---- MM Medic materials notifications ----

    @staticmethod
    def _materials_admin_url(instance_id):
        from app.models.site_settings import SiteSettings
        base = (SiteSettings.get().website_url or '').rstrip('/')
        tail = f'/admin/instances/{instance_id}/materials'
        return f'{base}{tail}' if base else tail

    @staticmethod
    def _materials_context(reservation, instance):
        return {
            'event_title': (instance.course.title if instance and instance.course else 'Захід'),
            'event_date': (instance.start_date.strftime('%d.%m.%Y')
                           if instance and instance.start_date else None),
            'event_location': getattr(instance, 'location', None) if instance else None,
            'items': list(reservation.items),
        }

    @staticmethod
    def send_materials_actuals_reminder(reservation, instance):
        """Remind admins/managers to submit actuals for an ended reservation."""
        from app.services.notification_recipients import resolve
        recipients = resolve('materials', instance=instance)
        if not recipients:
            return []
        ctx = EmailService._materials_context(reservation, instance)
        ctx['admin_url'] = EmailService._materials_admin_url(
            instance.id if instance else reservation.instance_id
        )
        return EmailService._send_to_recipients(
            recipients,
            subject=f'Внесіть фактичні матеріали: {ctx["event_title"]}',
            template_name='materials_actuals_reminder',
            context=ctx,
            trigger='materials',
            registration_id=None,
        )

    @staticmethod
    def send_course_request_received(course_request):
        """Підтвердити клієнту, що його запит на курс отримано.

        Шлеться на email, який клієнт ввів у форму. Окремий лист від
        admin-нотифікації -- різні to_email і шаблон, але той самий
        trigger='course_request' (бізнес-подія одна).
        """
        if not course_request.email:
            logger.warning(
                'CourseRequest #%s has no client email -- skipping ack',
                course_request.id,
            )
            return None

        course = course_request.course
        subject = (
            f'Ми отримали ваш запит: {course.title}'
            if course else 'Ми отримали ваш запит'
        )

        # Завжди беремо base з site_settings.website_url (див. коментар у
        # send_course_request_notification щодо url_for vs SERVER_NAME).
        from app.models.site_settings import SiteSettings
        base = (SiteSettings.get().website_url or '').rstrip('/')
        course_url = (
            f'{base}/courses/{course.slug}'
            if course is not None and base else None
        )

        return EmailService.send_email(
            to=course_request.email,
            subject=subject,
            template_name='course_request_received',
            context={
                'request_obj': course_request,
                'course': course,
                'course_url': course_url,
            },
            trigger='course_request',
        )

    @staticmethod
    def send_test_email(to):
        """Send test email synchronously so SMTP errors propagate to caller."""
        app = current_app._get_current_object()

        with app.app_context():
            smtp_cfg = _get_smtp_config(app)

        if not smtp_cfg['is_enabled']:
            log_entry = EmailLog(
                to_email=to,
                subject='Тестовий лист | ІПРМ',
                template_name='test',
                status='failed',
                error_message='Email sending is disabled in settings',
                trigger='test',
            )
            db.session.add(log_entry)
            db.session.commit()
            raise RuntimeError('Email sending is disabled in settings')

        if not smtp_cfg['server'] or not smtp_cfg['username']:
            raise RuntimeError('SMTP сервер або логін не налаштовані')

        if not smtp_cfg['has_password']:
            raise RuntimeError('SMTP пароль не налаштований')

        html_body = render_template('emails/test.html', to_email=to)
        plain_body = _html_to_plaintext(html_body)
        msg = Message(
            subject='Тестовий лист | ІПРМ',
            recipients=[to],
            html=html_body,
            body=plain_body,
            sender=smtp_cfg['sender'],
        )

        log_entry = EmailLog(
            to_email=to,
            subject='Тестовий лист | ІПРМ',
            template_name='test',
            status='pending',
            trigger='test',
            html_body=html_body,
        )
        db.session.add(log_entry)
        db.session.commit()

        try:
            _smtp_send(msg, smtp_cfg)
            log_entry.status = 'sent'
            log_entry.sent_at = datetime.now(timezone.utc)
            db.session.commit()
            logger.info('Test email sent to %s', to)
        except Exception as exc:
            log_entry.status = 'failed'
            log_entry.error_message = str(exc)[:500]
            db.session.commit()
            logger.exception('Failed to send test email to %s', to)
            raise
        return log_entry

    # ---- Queue maintenance ----

    @staticmethod
    def cleanup_stale_pending():
        """Mark emails stuck in 'pending' longer than STALE_PENDING_MINUTES as failed.

        Uses batch UPDATE for efficiency.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_PENDING_MINUTES)
        count = EmailLog.query.filter(
            EmailLog.status == 'pending',
            EmailLog.created_at < cutoff,
        ).update({
            EmailLog.status: 'failed',
            EmailLog.error_message: f'Timeout: stuck in pending >{STALE_PENDING_MINUTES} min',
        }, synchronize_session=False)

        if count:
            db.session.commit()
            logger.info('Cleaned up %d stale pending emails', count)

        return count

    @staticmethod
    def retry_failed_emails():
        """Retry failed emails using saved html_body (no re-render needed).

        Eligible: transient errors, under max retries, last hour, not test.
        Skips if circuit breaker is open.
        """
        from app.models.email_settings import EmailSettings
        settings = EmailSettings.get()
        if not settings.is_enabled:
            return 0

        if EmailService._check_circuit_breaker():
            logger.warning('Circuit breaker open: skipping retry cycle')
            return 0

        smtp_cfg = _get_smtp_config(current_app._get_current_object())

        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        failed = EmailLog.query.filter(
            EmailLog.status == 'failed',
            EmailLog.retry_count < MAX_RETRIES,
            EmailLog.trigger != 'test',
            EmailLog.created_at >= cutoff,
            EmailLog.html_body.isnot(None),
        ).order_by(EmailLog.created_at.asc()).limit(10).all()

        sender_addr = _sender_address(smtp_cfg['sender'])
        prepared = []  # (entry, msg) -- готуємо до відправки одним з'єднанням
        for entry in failed:
            if not entry.is_retryable:
                continue
            entry.retry_count += 1
            entry.status = 'pending'
            msg = Message(
                subject=entry.subject,
                recipients=[entry.to_email],
                html=entry.html_body,
                body=_html_to_plaintext(entry.html_body),
                sender=smtp_cfg['sender'],
                reply_to=sender_addr,
            )
            prepared.append((entry, msg))

        if not prepared:
            return 0
        db.session.flush()

        try:
            results = _smtp_send_many([m for _, m in prepared], smtp_cfg)
        except Exception as exc:  # з'єднання не відкрилось -- лишаємо failed
            for entry, _ in prepared:
                entry.status = 'failed'
                entry.error_message = f'Retry {entry.retry_count} connect failed: {str(exc)[:300]}'
            db.session.commit()
            logger.warning('Retry batch connect failed: %s', exc)
            return 0

        err_by_msg = {id(m): err for m, err in results}
        retried = 0
        for entry, msg in prepared:
            err = err_by_msg.get(id(msg))
            if err is None:
                entry.status = 'sent'
                entry.sent_at = datetime.now(timezone.utc)
                entry.error_message = None
                retried += 1
            else:
                entry.status = 'failed'
                entry.error_message = f'Retry {entry.retry_count} failed: {str(err)[:400]}'
                logger.warning('Retry FAILED: id=%s to=%s (attempt %d): %s',
                               entry.id, entry.to_email, entry.retry_count, err)
        db.session.commit()

        if retried:
            logger.info('Retried %d/%d failed emails (1 conn)', retried, len(prepared))

        return retried

    @staticmethod
    def manual_resend(log_id):
        """Manual one-shot resend (admin-trigger). На відміну від
        retry_failed_emails -- без cutoff/MAX_RETRIES/circuit-breaker
        обмежень: адмін явно тисне кнопку, тож обмеження не доречні.

        Повертає (ok: bool, message: str). Не raise -- caller flash-ить
        результат.
        """
        from app.models.email_settings import EmailSettings

        entry = db.session.get(EmailLog, log_id)
        if not entry:
            return False, 'Лог не знайдено'

        if not entry.html_body:
            return False, 'Немає збереженого html_body для повторної відправки'

        settings = EmailSettings.get()
        if not settings.is_enabled:
            return False, 'SMTP-відправку вимкнено в налаштуваннях'

        smtp_cfg = _get_smtp_config(current_app._get_current_object())

        entry.retry_count = (entry.retry_count or 0) + 1
        entry.status = 'pending'
        db.session.flush()

        try:
            plain_body = _html_to_plaintext(entry.html_body)
            msg = Message(
                subject=entry.subject,
                recipients=[entry.to_email],
                html=entry.html_body,
                body=plain_body,
                sender=smtp_cfg['sender'],
            )
            _smtp_send(msg, smtp_cfg)
            entry.status = 'sent'
            entry.sent_at = datetime.now(timezone.utc)
            entry.error_message = (entry.error_message or '') + '\n[admin-resend OK]'
            db.session.commit()
            logger.info('Manual resend OK: id=%s to=%s', entry.id, entry.to_email)
            return True, f'Лист #{entry.id} відправлено на {entry.to_email}'
        except Exception as exc:
            entry.status = 'failed'
            entry.error_message = f'Manual resend failed: {str(exc)[:400]}'
            db.session.commit()
            logger.warning('Manual resend FAILED: id=%s: %s', entry.id, exc)
            return False, f'Помилка при відправці: {str(exc)[:200]}'
