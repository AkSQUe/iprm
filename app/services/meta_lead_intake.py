"""Постановка події leadgen у вхідну чергу.

Модуль навмисно крихітний і навмисно окремий від воркера черги
(`meta_lead_queue`): КЛАСТИ в чергу треба двом незалежним сторонам --
вебхуку (`app/api/meta_leads.py`) і звірці, -- а ЗАБИРАТИ лише воркеру.
Межа проведена по напрямку руху даних, тож обидва відправники користуються
однією реалізацією ідемпотентності замість двох схожих.

Тут не робиться жодного походу в Graph API. Подія -- це лише запис
"сходи по цей лід згодом": вебхук мусить відповісти Meta за секунди,
інакше доставка вважається невдалою і починаються ретраї.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.meta_lead import MetaLeadEvent

logger = logging.getLogger(__name__)

_ALLOWED_SOURCES = (
    MetaLeadEvent.SOURCE_WEBHOOK,
    MetaLeadEvent.SOURCE_RECONCILE,
    MetaLeadEvent.SOURCE_MANUAL,
)

# Довжина колонок ідентифікаторів Meta.
_ID_LENGTH = 64


def _identifier(value):
    """Ідентифікатор Meta як рядок, або None.

    Задовгі значення відкидаємо, а не обрізаємо: обрізаний ідентифікатор --
    це ІНШИЙ об'єкт, і мовчазна підміна form_id гірша за його відсутність
    (PostgreSQL на такому впав би, SQLite мовчки записав би сміття).
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or len(text) > _ID_LENGTH:
        return None
    return text


def _created_time(raw):
    """Час створення ліда -> aware UTC.

    Вебхук приносить unix-число, звірка -- ISO-рядок Graph API зі зсувом
    без двокрапки (`+0000`), який `fromisoformat` до 3.11 не розбирає.
    Обидві форми ходять в ОДНУ колонку, тож розбираються тут, а не в
    кожного відправника окремо.
    """
    if raw is None or raw == '':
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(raw).strip()
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = text.replace('Z', '+00:00')
    if len(text) >= 5 and text[-5] in '+-' and text[-3] != ':':
        text = f'{text[:-2]}:{text[-2:]}'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _find_existing(leadgen_id):
    """Чи вже є така подія в черзі.

    Окремою функцією не заради краси: гон двох воркерів інакше неможливо
    відтворити в тесті -- обидва мусять побачити ПОРОЖНІЙ результат, а
    підмінити всередині одного процесу можна лише названий шов.
    """
    return MetaLeadEvent.query.filter_by(leadgen_id=leadgen_id).first()


def enqueue_event(value, source=MetaLeadEvent.SOURCE_WEBHOOK):
    """Покласти сиру подію leadgen у чергу. Повертає подію або None (дубль).

    `value` -- вміст `entry[].changes[].value` вебхука або еквівалентний
    dict зі звірки. Зберігається ЦІЛКОМ і не редагується: якщо розбір
    згодом виявиться помилковим, переграти його можна лише з оригіналу.

    Ідемпотентність тримається на UNIQUE `leadgen_id`, а не на перевірці
    "спершу SELECT, потім INSERT": Meta доставляє повтор при кожному
    сумніві, і дві доставки цілком можуть потрапити в РІЗНІ gunicorn-воркери
    одночасно -- обидва побачать порожній SELECT. Тому SELECT тут лише
    економить вставку в частому випадку, а справжній захист -- перехоплений
    `IntegrityError`.

    Commit робиться тут, по одній події. Це не зайва скрупульозність:
    відкат після програного гону інакше змив би й попередні події з того
    самого пакета вебхука (Meta шле кілька `changes[]` в одному тілі), а
    SAVEPOINT на pysqlite поводиться так, що тести почали б брехати.
    """
    if source not in _ALLOWED_SOURCES:
        # Джерело задає НАШ код, не payload, тож це помилка програміста, а
        # не поганий вхід -- ховати її за дефолтом означало б отримати
        # CHECK-порушення на commit у зовсім іншому місці.
        raise ValueError(f'unknown meta lead event source: {source!r}')

    if not isinstance(value, dict):
        logger.warning('Meta leadgen event ignored: value is %s, not a dict',
                       type(value).__name__)
        return None

    leadgen_id = _identifier(value.get('leadgen_id'))
    if not leadgen_id:
        # Без ідентифікатора подія марна: забрати за нею нічого.
        logger.warning('Meta leadgen event ignored: no usable leadgen_id (source=%s)',
                       source)
        return None

    existing = _find_existing(leadgen_id)
    if existing is not None:
        logger.info('Meta leadgen event %s already queued (source=%s, status=%s)',
                    leadgen_id, source, existing.status)
        return None

    event = MetaLeadEvent(
        leadgen_id=leadgen_id,
        page_id=_identifier(value.get('page_id')),
        form_id=_identifier(value.get('form_id')),
        ad_id=_identifier(value.get('ad_id')),
        created_time=_created_time(value.get('created_time')),
        received_at=datetime.now(timezone.utc),
        raw_payload=dict(value),
        source=source,
        status=MetaLeadEvent.STATUS_PENDING,
    )
    db.session.add(event)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        logger.info('Meta leadgen event %s lost the insert race (source=%s)',
                    leadgen_id, source)
        return None

    # У лог іде ЛИШЕ ідентифікатор. Вміст полів форми -- персональні дані,
    # і місце їм у базі, а не в текстових логах на диску.
    logger.info('Meta leadgen event %s queued (source=%s, event_id=%s)',
                leadgen_id, source, event.id)
    return event
