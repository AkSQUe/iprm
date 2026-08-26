"""Вхідна черга лідів Meta: воркер, звірка, стан токена, моніторинг.

Це шов інтеграції: сюди сходяться прийом (`meta_lead_intake`), клієнт
Graph API (`meta_graph_client`), розбір (`meta_lead_ingest`) і партнерська
черга (`partner_events`). Власної доменної логіки тут майже немає -- є
порядок і межі транзакцій, а саме на них ця інтеграція й ламається.

Чому черга окрема від `webhook_queue`. Та -- ВИХІДНА: рядок означає
"відправ партнеру, ретрай при 5xx". Ця -- ВХІДНА: рядок означає "сходи в
Graph API і забери лід". Спільним лишається підхід (backoff 1/2/4/8/16 хв,
стеля спроб, збережений текст помилки), а не таблиця й не код: складені
разом, вони дали б CHECK із двох взаємовиключних форм і розвилку на
кожному кроці.

Три межі, які тут не можна переставляти:

* **`enqueue_event` комітить сама, поштучно.** Тому все, що звірка пише в
  налаштування, пишеться ПІСЛЯ циклу постановки: інакше напівготовий стан
  прогону поїхав би в базу разом із першою ж подією.
* **`ingest_lead` не комітить.** Подія, лід і контакт лягають однією
  транзакцією -- інакше лід існував би без позначки в події, і наступний
  прогін завів би його вдруге.
* **Партнерська подія емітиться ПІСЛЯ коміту.** Подія про заявку, яку ще
  може відкотити, -- це подія про те, чого не сталося.

У лог іде лише `leadgen_id`. Вміст полів форми -- персональні дані, і
місце їм у базі, а не в текстових логах на диску.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.meta_lead import (
    EVENT_INITIAL_BACKOFF_SECONDS,
    MAX_EVENT_ATTEMPTS,
    MetaLead,
    MetaLeadEvent,
)
from app.models.mixins import utcnow
from app.models.site_settings import SiteSettings
from app.services import partner_events
from app.services.meta_graph_client import MetaConfigError, MetaGraphClient
from app.services.meta_lead_ingest import MetaIngestError, ingest_lead
from app.services.meta_lead_intake import enqueue_event
from app.utils import ensure_utc

logger = logging.getLogger(__name__)

# Скільки подій обробляти за прогін. Воркер ходить щохвилини, тож ліміт --
# захист від довгої джоби на розгрібанні завалу, а не стеля пропускної
# здатності.
BATCH_LIMIT = 25

# Форми, з яких звірка добирає ліди. Meta лишає в переліку і чернетки, і
# архівні форми -- ходити по них означало б витрачати квоту на те, що
# завідомо порожнє.
ACTIVE_FORM_STATUSES = ('ACTIVE',)

# Не частіше разу на добу на всі три сигнали разом. Тиша при активних
# формах не мине сама, і лист про неї щогодини лише навчить менеджера
# ігнорувати цю адресу.
ALERT_MIN_INTERVAL_HOURS = 24

# Скільки годин назад рахуємо помилки черги для алерту.
ERROR_WINDOW_HOURS = 24

# Тексти помилок ідуть у колонки й у листи -- обрізаємо, щоб полотно
# трасування з Graph API не роздувало рядок.
_ERROR_TEXT_LIMIT = 2000


def _client(settings):
    """Клієнт Graph API з налаштувань.

    Названий шов: тести підміняють саме його, бо доступів Meta на час
    розробки немає, а сім критеріїв приймання з восьми перевіряються без
    жодного походу в мережу.
    """
    return MetaGraphClient.from_settings(settings)


def _as_utc(value):
    """Наївна дата з SQLite -> aware UTC.

    `DateTime(timezone=True)` на SQLite повертається БЕЗ tzinfo, і
    порівняння з `utcnow()` падає TypeError. У проді (PostgreSQL) значення
    вже aware, тож функція нічого не змінює -- вона потрібна рівно для
    того, щоб тести не брехали про робочий код.
    """
    value = ensure_utc(value)
    return value.astimezone(timezone.utc) if value is not None else None


# --- воркер черги ---------------------------------------------------------

def process_queue(limit=BATCH_LIMIT):
    """Забрати з Graph API ліди за подіями черги. Повертає статистику.

    Обробка гейтиться на `meta_leads_enabled`, а прийом (вебхук) -- ні:
    вимкнений прапорець має відкласти похід у Graph API, а не втратити
    заявку. Події лишаються `pending` і дочекаються вмикання.
    """
    stats = {'processed': 0, 'done': 0, 'retrying': 0, 'failed': 0, 'skipped': 0}

    settings = SiteSettings.get()
    if not settings.meta_leads_enabled:
        stats['reason'] = 'integration disabled'
        return stats

    try:
        client = _client(settings)
    except MetaConfigError as exc:
        # Недоналаштована інтеграція -- не привід палити спроби: подія без
        # токена не стане валідною від п'ятої спроби, а `failed` довелося б
        # скидати руками після ротації.
        logger.warning('meta_lead_queue: %s', exc)
        stats['reason'] = str(exc)
        return stats

    now = utcnow()
    candidates = (
        MetaLeadEvent.query
        .filter(
            db.or_(
                MetaLeadEvent.status == MetaLeadEvent.STATUS_PENDING,
                db.and_(
                    MetaLeadEvent.status == MetaLeadEvent.STATUS_RETRYING,
                    MetaLeadEvent.next_retry_at <= now,
                ),
            )
        )
        .order_by(MetaLeadEvent.received_at.asc())
        .limit(limit)
        .all()
    )

    for event in candidates:
        stats['processed'] += 1
        outcome, lead = _process_event(event, client)
        stats[outcome] = stats.get(outcome, 0) + 1
        if lead is not None:
            _emit_lead(lead)

    if stats['processed']:
        logger.info('meta_lead_queue: %s', stats)
    return stats


def _process_event(event, client):
    """Один рядок черги. Комітить сам; повертає (результат, лід або None).

    Лід повертається лише тоді, коли його справді щойно створено: саме за
    ним потім іде партнерська подія, і повторний прогін не має слати її
    вдруге.
    """
    event_id = event.id
    leadgen_id = event.leadgen_id
    attempts = (event.attempts or 0) + 1

    result = client.get_lead(leadgen_id)
    if not result.ok:
        # `retryable` уже класифікував клієнт -- лише він бачить код
        # помилки Meta. Перевизначати його тут означало б мати дві
        # класифікації, які розійдуться на першому новому коді.
        return _mark_failure(event_id, attempts, result.error,
                             retryable=result.retryable,
                             leadgen_id=leadgen_id), None

    existing = MetaLead.query.filter_by(leadgen_id=leadgen_id).first()
    if existing is not None:
        # Лід уже розібрано раніше (ретрай після часткового збою, ручний
        # повтор події). Це не помилка й не привід заводити другу картку.
        event.attempts = attempts
        event.status = MetaLeadEvent.STATUS_SKIPPED
        event.processed_at = utcnow()
        event.last_error = None
        event.next_retry_at = None
        # На видалену заявку не посилаємось: подія й існує для того, щоб
        # повторна доставка НЕ воскресила те, що адмін прибрав.
        event.lead_id = None if existing.is_deleted else existing.id
        db.session.commit()
        logger.info('meta_lead_queue: %s already ingested, event marked skipped',
                    leadgen_id)
        return 'skipped', None

    try:
        lead = ingest_lead(result.data, event=event)
        event.attempts = attempts
        event.status = MetaLeadEvent.STATUS_DONE
        event.lead_id = lead.id
        event.processed_at = utcnow()
        event.last_error = None
        event.next_retry_at = None
        # Позначка часу ПРИЙОМУ, а не `created_time` ліда: звірка тягне і
        # старі заявки, і від них позначка їхала б назад, а на ній тримається
        # алерт про тишу.
        settings = SiteSettings.get()
        settings.meta_last_lead_at = utcnow()
        db.session.commit()
    except MetaIngestError as exc:
        # Відповідь Graph API без ідентифікатора ліда. Від повтору вона не
        # виправиться, тож спроби не палимо -- одразу діагноз.
        db.session.rollback()
        return _mark_failure(event_id, attempts, str(exc), retryable=False,
                             leadgen_id=leadgen_id), None
    except Exception as exc:
        db.session.rollback()
        logger.exception('meta_lead_queue: ingest of %s failed', leadgen_id)
        return _mark_failure(event_id, attempts, f'{type(exc).__name__}: {exc}',
                             retryable=True, leadgen_id=leadgen_id), None

    logger.info('meta_lead_queue: %s ingested as lead id=%s', leadgen_id, lead.id)
    return 'done', lead


def _mark_failure(event_id, attempts, error, *, retryable, leadgen_id):
    """Записати невдачу спроби: ретрай із backoff або остаточна поразка.

    Подія перечитується з бази за id, бо шлях сюди веде і після
    `rollback()`, після якого об'єкт у руках викликача вже не має ані
    лічильника спроб, ані гарантії, що він лишився в сесії.
    """
    event = db.session.get(MetaLeadEvent, event_id)
    if event is None:
        return 'failed'

    event.attempts = attempts
    event.last_error = (error or 'Невідома помилка')[:_ERROR_TEXT_LIMIT]

    if retryable and attempts < MAX_EVENT_ATTEMPTS:
        event.status = MetaLeadEvent.STATUS_RETRYING
        event.next_retry_at = _next_retry_at(attempts)
        outcome = 'retrying'
        logger.warning('meta_lead_queue: %s retry %d/%d -- %s',
                       leadgen_id, attempts, MAX_EVENT_ATTEMPTS, event.last_error)
    else:
        event.status = MetaLeadEvent.STATUS_FAILED
        event.next_retry_at = None
        outcome = 'failed'
        logger.error('meta_lead_queue: %s FAILED after %d attempts -- %s',
                     leadgen_id, attempts, event.last_error)

    db.session.commit()
    return outcome


def _next_retry_at(attempts):
    """Exponential backoff 1/2/4/8/16 хв від бази 60 с."""
    seconds = EVENT_INITIAL_BACKOFF_SECONDS * (2 ** (attempts - 1))
    return utcnow() + timedelta(seconds=seconds)


def _emit_lead(lead):
    """Розповісти партнеру про заявку -- строго після коміту.

    Відсів тестових заявок і заявок без контактів робить сам
    `emit_lead_created`; дублювати ту перевірку тут означало б два місця
    правди про те, кого показувати партнеру.

    Збій партнерської черги не має валити прогін: лід уже наш, подія --
    справа наступного прогону або ручного повтору в адмінці.
    """
    try:
        partner_events.emit_lead_created(lead)
    except Exception:
        logger.exception('meta_lead_queue: partner event for lead id=%s failed',
                         lead.id)


# --- звірка ---------------------------------------------------------------

def reconcile(lookback_hours=None):
    """Добрати ліди, які не доїхали вебхуком. Повертає статистику.

    Вебхук Meta -- доставка "зазвичай", а не "завжди": підписку вимикають
    після серії невдач, а самі ліди живуть у Meta лише 90 днів. Звірка
    перечитує останні кілька годин і кладе в чергу все, чого немає, --
    саме вона й закриває критерій приймання N7.

    Інтервал тут НЕ перевіряється: ту саму функцію тисне кнопка "звірити
    зараз" в адмінці, і чекати від неї півгодини було б знущанням. Час
    чергового прогону звіряє джоба через `reconcile_is_due`.
    """
    stats = {'checked_forms': 0, 'fetched': 0, 'created': 0, 'skipped': 0}

    settings = SiteSettings.get()
    if not settings.meta_leads_enabled:
        stats['reason'] = 'integration disabled'
        return stats

    page_id = (settings.meta_page_id or '').strip()
    if not page_id:
        stats['reason'] = 'no page id'
        return stats

    try:
        client = _client(settings)
    except MetaConfigError as exc:
        stats['reason'] = str(exc)
        _finish_reconcile('error', str(exc))
        return stats

    if lookback_hours is None:
        lookback_hours = settings.meta_reconcile_lookback_hours or 48
    since_ts = int((utcnow() - timedelta(hours=lookback_hours)).timestamp())

    forms_result = client.list_page_forms(page_id)
    if not forms_result.ok:
        stats['reason'] = forms_result.error
        _finish_reconcile('error', forms_result.error)
        return stats

    errors = []
    for form in forms_result.data or []:
        if not isinstance(form, dict):
            continue
        form_id = str(form.get('id') or '').strip()
        if not form_id:
            continue
        form_status = str(form.get('status') or '').upper()
        if form_status and form_status not in ACTIVE_FORM_STATUSES:
            continue

        stats['checked_forms'] += 1
        leads_result = client.list_form_leads(form_id, since_ts)
        if not leads_result.ok:
            # Одна форма, що відмовила, не має зупиняти решту: у Сторінки
            # їх десятки, і збій на першій сховав би всі інші.
            errors.append(f'{form_id}: {leads_result.error}')
            continue

        for raw in leads_result.data or []:
            if not isinstance(raw, dict):
                continue
            stats['fetched'] += 1
            # Дубль відсіює сам `enqueue_event` (UNIQUE leadgen_id):
            # власна пре-перевірка тут була б другою копією тієї самої
            # ідемпотентності, яка розійшлася б із першою.
            if enqueue_event(_reconciled_value(raw, page_id, form_id),
                             source=MetaLeadEvent.SOURCE_RECONCILE) is None:
                stats['skipped'] += 1
            else:
                stats['created'] += 1

    status = 'partial' if errors else 'ok'
    # Стан прогону пишеться ТІЛЬКИ тут, після циклу: `enqueue_event`
    # комітить сама, і напівзаповнений результат поїхав би в базу разом із
    # першою ж поставленою подією.
    _finish_reconcile(status, '; '.join(errors))
    if errors:
        logger.warning('meta_lead_queue reconcile finished with errors: %s', errors)
    logger.info('meta_lead_queue reconcile: %s', stats)
    return stats


def _reconciled_value(raw_lead, page_id, form_id):
    """Відповідь Graph API -> `value`, який розуміє `enqueue_event`.

    Повні дані ліда сюди не кладемо навмисно: подія лишається однією й тією
    самою незалежно від джерела, а забирає лід завжди воркер. Інакше було б
    два шляхи розбору -- і другий, рідкісний, ніхто б не супроводжував.
    """
    return {
        'leadgen_id': raw_lead.get('id'),
        'page_id': page_id,
        'form_id': raw_lead.get('form_id') or form_id,
        'ad_id': raw_lead.get('ad_id'),
        'created_time': raw_lead.get('created_time'),
    }


def _finish_reconcile(status, error=''):
    """Підсумок прогону в налаштування -- для сторінки стану інтеграції."""
    settings = SiteSettings.get()
    settings.meta_last_reconcile_at = utcnow()
    settings.meta_last_reconcile_status = status
    settings.meta_last_reconcile_error = (error or '')[:_ERROR_TEXT_LIMIT]
    db.session.commit()


def reconcile_is_due(now=None):
    """Чи настав час чергового прогону звірки.

    Період живе в налаштуваннях і змінюється в адмінці без перезапуску
    процесу, тож у cron-виразі його тримати не можна -- джоба ходить часто
    й питає тут. Той самий підхід, що `sintegrum_sync_is_due`.
    """
    settings = SiteSettings.get()
    if not settings.meta_leads_enabled:
        return False

    interval = settings.meta_reconcile_interval_minutes or 30
    last = _as_utc(settings.meta_last_reconcile_at)
    if last is None:
        return True
    return ((now or utcnow()) - last) >= timedelta(minutes=interval)


# --- стан токена ----------------------------------------------------------

def check_token():
    """`debug_token`: чи живий Page token, доки і з якими дозволами.

    Ті самі колонки пише кнопка "перевірити зараз" в адмінці. Двоє писців
    тут не конфлікт: обидва пишуть підсумок ОДНІЄЇ й тієї самої відповіді
    Meta, а не свою версію правди.
    """
    report = {'checked': False, 'valid': None, 'permanent': False,
              'expires_at': None, 'scopes': [], 'error': ''}

    settings = SiteSettings.get()
    if not settings.meta_leads_enabled:
        report['error'] = 'integration disabled'
        return report

    try:
        client = _client(settings)
    except MetaConfigError as exc:
        # Недоналаштована інтеграція -- це не "токен недійсний": писати
        # сюди False означало б підняти алерт про поламаний токен там, де
        # його ще просто не заводили.
        report['error'] = str(exc)
        return report

    result = client.debug_token()
    settings.meta_token_checked_at = utcnow()
    report['checked'] = True

    if result.ok and isinstance(result.data, dict):
        data = result.data
        expires = int(data.get('expires_at') or 0)
        settings.meta_token_valid = bool(data.get('is_valid'))
        # 0 означає БЕЗСТРОКОВИЙ -- саме таким і має бути Page token,
        # обміняний через довгоживучий User token. Трактувати нуль як
        # unix-час дало б "протух 01.01.1970" і щоденний алерт на рівному
        # місці.
        settings.meta_token_expires_at = (
            datetime.fromtimestamp(expires, tz=timezone.utc) if expires else None
        )
        settings.meta_token_error = ''
        report['valid'] = settings.meta_token_valid
        report['permanent'] = expires == 0
        report['expires_at'] = settings.meta_token_expires_at
        report['scopes'] = list(data.get('scopes') or [])
    else:
        settings.meta_token_valid = False
        settings.meta_token_error = (result.error or 'Невідома помилка')[:_ERROR_TEXT_LIMIT]
        report['valid'] = False
        report['error'] = settings.meta_token_error

    db.session.commit()
    logger.info('meta_lead_queue: token check valid=%s permanent=%s',
                report['valid'], report['permanent'])
    return report


# --- моніторинг -----------------------------------------------------------

def run_health_alerts(now=None):
    """Три сигнали про те, що приймання лідів зламалось.

    Листа на кожен лід ми свідомо не шлемо (рішення Q9) -- отже єдиний
    спосіб дізнатись про поламане приймання це моніторинг. Сигналів три, а
    подія одна: для менеджера "реклама йде, а заявок немає", "черга сипле
    помилками" і "токен відкликано" -- це один і той самий висновок.
    """
    report = {'sent': False, 'reasons': [], 'failed_events': 0}

    settings = SiteSettings.get()
    if not settings.meta_leads_enabled:
        report['reason'] = 'integration disabled'
        return report

    now = now or utcnow()
    reasons = []

    silence = _silence_reason(settings, now)
    if silence is not None:
        reasons.append(silence)

    failed_count = _failed_events_count(now)
    report['failed_events'] = failed_count
    threshold = settings.meta_error_alert_threshold or 0
    if threshold > 0 and failed_count >= threshold:
        reasons.append({
            'code': 'errors',
            'title': 'Помилки в черзі приймання',
            'detail': (
                f'За останні {ERROR_WINDOW_HOURS} год {failed_count} '
                f'подій leadgen так і не вдалося забрати з Graph API '
                f'(поріг -- {threshold}). Заявки за ними в адмінку не потрапили.'
            ),
        })

    if settings.meta_token_valid is False:
        reasons.append({
            'code': 'token',
            'title': 'Токен Сторінки недійсний',
            'detail': (
                'Meta вважає Page Access Token недійсним. Доки його не '
                'обміняно заново, жодна заявка не буде забрана з Graph API. '
                + (settings.meta_token_error or '')
            ).strip(),
        })

    report['reasons'] = reasons
    if not reasons:
        return report

    last_alert = _as_utc(settings.meta_alert_sent_at)
    if last_alert is not None and (now - last_alert) < timedelta(hours=ALERT_MIN_INTERVAL_HOURS):
        # Тиша не мине сама, і лист про неї щогодини навчить менеджера
        # ігнорувати цю адресу -- разом із листами, що справді важливі.
        report['reason'] = 'throttled'
        return report

    from app.services.email_service import EmailService
    try:
        EmailService.send_meta_leads_alert(reasons, stats={
            'failed_events': failed_count,
            'last_lead_at': _as_utc(settings.meta_last_lead_at),
            'last_webhook_at': _as_utc(settings.meta_last_webhook_at),
            'last_reconcile_at': _as_utc(settings.meta_last_reconcile_at),
        })
    except Exception:
        # Позначку часу НЕ ставимо: інакше збій пошти вимкнув би сигнал на
        # добу, і саме тоді, коли він потрібен.
        logger.exception('meta_lead_queue: health alert email failed')
        report['reason'] = 'email failed'
        return report

    settings.meta_alert_sent_at = now
    db.session.commit()
    report['sent'] = True
    logger.warning('meta_lead_queue health alert sent: %s',
                   [r['code'] for r in reasons])
    return report


def _silence_reason(settings, now):
    """Тиша при активних формах -- або None, якщо сигналу немає.

    Дві умови разом, а не одна: сама по собі відсутність заявок нічого не
    означає (кампанію могли зупинити), а сама по собі активна форма -- тим
    паче. Тривожно саме поєднання: реклама йде, а заявок немає.
    """
    hours = settings.meta_silence_alert_hours or 0
    if hours <= 0:
        return None

    since = _as_utc(settings.meta_last_lead_at)
    if since is None:
        # Жодної заявки ще не було. Точкою відліку беремо момент, коли
        # інтеграція стала робочою (з'явився токен Сторінки): без неї
        # свіжо налаштована інтеграція волала б про тишу з першого дня.
        since = _as_utc(settings.meta_page_token_set_at)
    if since is None or (now - since) < timedelta(hours=hours):
        return None

    if not _has_active_forms(settings):
        return None

    idle_hours = int((now - since).total_seconds() // 3600)
    return {
        'code': 'silence',
        'title': 'Заявок немає, а форми активні',
        'detail': (
            f'Остання заявка з Meta прийшла {idle_hours} год тому, '
            f'хоча на Сторінці є активні форми. Перевірте підписку на '
            f'leadgen, токен і доставку вебхука.'
        ),
    }


def _has_active_forms(settings):
    """Чи є на Сторінці хоч одна активна форма.

    Похід у Graph API робиться ЛИШЕ коли вікно тиші вже вичерпане: питати
    про форми щодня заради сигналу, якого немає, означало б палити квоту.
    Невідома відповідь трактується як "форм немає": кричати про тишу, не
    змігши перевірити другу половину умови, -- це хибний сигнал.
    """
    page_id = (settings.meta_page_id or '').strip()
    if not page_id:
        return False
    try:
        client = _client(settings)
    except MetaConfigError:
        return False

    result = client.list_page_forms(page_id)
    if not result.ok:
        logger.warning('meta_lead_queue: cannot list forms for silence check -- %s',
                       result.error)
        return False

    for form in result.data or []:
        if not isinstance(form, dict):
            continue
        status = str(form.get('status') or '').upper()
        if not status or status in ACTIVE_FORM_STATUSES:
            return True
    return False


def _failed_events_count(now):
    """Скільки подій остаточно провалилось за вікно спостереження.

    Рахуємо за `updated_at`, а не за `received_at`: подія могла прийти три
    доби тому і провалитись сьогодні -- саме сьогоднішній провал і є
    новиною.
    """
    cutoff = now - timedelta(hours=ERROR_WINDOW_HOURS)
    return (
        MetaLeadEvent.query
        .filter(MetaLeadEvent.status == MetaLeadEvent.STATUS_FAILED,
                MetaLeadEvent.updated_at >= cutoff)
        .count()
    )
