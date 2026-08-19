"""Що ми розповідаємо партнеру про реєстрації та листи.

Партнер (MM Medic) веде єдину базу клієнтів: та сама людина, яка вчиться в
нас, купує в нього розхідники. Досі назовні йшов лише каталог курсів, тож у
картці клієнта не було ані її навчання, ані нашого листування з нею — і
менеджер дзвонив із пропозицією рівно тоді, коли ми написали їй утретє за
тиждень.

**Подія — це ФАКТ із власним часом.** Каталожний вебхук («перечитай курс»)
можна повторити скільки завгодно й нічого не зіпсувати; реєстрацію чи
надісланий лист — ні. Тому тут інший підпис (із часовою міткою, отже із
захистом від повтору) і durable-черга з ідемпотентним ``event_uuid``.

**Слухачі на моделі, а не виклики в роутах.** Реєстрація створюється щонайменше
трьома шляхами (форма, адмінка, імпорт), а оплата змінюється ще й
LiqPay-колбеком. Розставляти виклики по кожному з них означає гарантовано
пропустити той, який додадуть наступним.

**Ставимо в чергу ПІСЛЯ коміту.** Подія про реєстрацію, яка ще може
відкотитись, — це подія про те, чого не сталося. Партнер уже завів картку, а
в нас порожньо.

**Порожній результат — не помилка.** Інтеграція може бути вимкнена; тоді
черга просто не наповнюється.
"""
import logging

from flask import has_app_context
from sqlalchemy import event as sa_event

logger = logging.getLogger(__name__)

_PENDING_KEY = '_iprm_partner_events_pending'

#: Стани, які партнер розуміє. Ключ — (status, payment_status, attended).
REGISTRATION_CREATED = 'registration.created'
REGISTRATION_PAID = 'registration.paid'
REGISTRATION_CANCELLED = 'registration.cancelled'
REGISTRATION_ATTENDED = 'registration.attended'
COMMUNICATION_SENT = 'communication.sent'
LEAD_CREATED = 'lead.created'


def _session_of(target, fallback_session):
    from app.extensions import db
    return db.session.object_session(target) or fallback_session


def _queue(session, event_type, payload):
    """Накопичити подію до кінця транзакції."""
    session.info.setdefault(_PENDING_KEY, []).append((event_type, payload))


def emit(event_type, payload):
    """Поставити подію в чергу негайно (поза транзакцією моделі).

    Для листів: вони відправляються у фоновому потоці, де транзакції моделі
    вже немає, і чекати «кінця транзакції» нема чого.
    """
    from app.services.webhook_queue import enqueue_partner_event

    try:
        return enqueue_partner_event(event_type, payload)
    except Exception:
        # Партнерська подія не має валити те, що її породило: людина вже
        # зареєструвалась, лист уже пішов.
        logger.exception('Failed to enqueue partner event %s', event_type)
        return None


def _registration_payload(registration):
    """Дані реєстрації для партнера — без зайвого.

    Медичні подробиці (ліцензія, стаж, місце роботи) назовні не йдуть: для
    того, щоб надіслати лист чи побачити дотик у картці, вони не потрібні, а
    мінімізація видачі — вимога до персональних даних.
    """
    instance = registration.instance
    course = getattr(instance, 'course', None) if instance is not None else None

    return {
        'registration_id': registration.id,
        'iprm_user_id': registration.user_id,
        'email': registration.user.email if registration.user else None,
        'instance_id': registration.instance_id,
        'course_slug': getattr(course, 'slug', None),
        'event_title': getattr(course, 'title', None),
        'status': registration.status,
        'payment_status': registration.payment_status,
        'attended': bool(registration.attended),
        'starts_at': (
            instance.starts_at.isoformat()
            if instance is not None and getattr(instance, 'starts_at', None) else None
        ),
    }


def register_registration_listeners(db) -> None:
    """Слухачі на реєстраціях: створення, оплата, скасування, присутність."""
    from app.models.registration import EventRegistration

    @sa_event.listens_for(EventRegistration, 'after_insert')
    def _on_insert(mapper, connection, target):
        _queue(_session_of(target, db.session), REGISTRATION_CREATED, target.id)

    @sa_event.listens_for(EventRegistration, 'after_update')
    def _on_update(mapper, connection, target):
        from sqlalchemy import inspect as sa_inspect

        state = sa_inspect(target)
        session = _session_of(target, db.session)

        # Читаємо саме ІСТОРІЮ поля, а не поточне значення: подія «оплачено»
        # має піти один раз, у момент переходу. Інакше будь-яке подальше
        # збереження оплаченої реєстрації повторювало б її знову й знову.
        payment_history = state.attrs.payment_status.history
        if payment_history.has_changes() and target.payment_status == 'paid':
            _queue(session, REGISTRATION_PAID, target.id)

        status_history = state.attrs.status.history
        if status_history.has_changes() and target.status == 'cancelled':
            _queue(session, REGISTRATION_CANCELLED, target.id)

        attended_history = state.attrs.attended.history
        if attended_history.has_changes() and target.attended:
            _queue(session, REGISTRATION_ATTENDED, target.id)

    @sa_event.listens_for(db.session, 'after_commit')
    def _on_commit(session):
        pending = session.info.pop(_PENDING_KEY, None)
        if not pending:
            return
        if not has_app_context():
            # Той самий запобіжник, що й у каталожного слухача: без контексту
            # читати налаштування нікуди, а мовчки загубити подію не можна —
            # пишемо в лог гучно.
            logger.warning(
                'Partner events dropped: no app context (%d pending)', len(pending),
            )
            return

        # Окрема короткоживуча сесія: `session` тут у стані 'committed', і
        # SQLAlchemy забороняє їй виконувати SQL. Той самий прийом, що і в
        # каталожного слухача — без нього подія падає з InvalidRequestError
        # рівно в проді, бо в тестах часто немає жодного lazy-load.
        from sqlalchemy.orm import Session

        with Session(db.engine) as reader:
            for event_type, registration_id in pending:
                registration = reader.get(EventRegistration, registration_id)
                if registration is None:
                    # Реєстрацію видалили в тій самій транзакції — розповідати
                    # нема про що.
                    continue
                emit(event_type, _registration_payload(registration))


def emit_communication_sent(log_entry) -> None:
    """Лист, який ми щойно надіслали учаснику.

    Викликається з потоку відправки: там уже немає ані транзакції моделі, ані
    гарантії, що сесія жива, тому подія ставиться в чергу одразу.

    Тіло листа НЕ передається — партнеру потрібен факт дотику, а не наш
    контент; зберігати чужі листи цілком у картці клієнта означало б
    дублювати поштову скриньку.
    """
    if log_entry is None or log_entry.status != 'sent':
        return

    emit(COMMUNICATION_SENT, {
        'external_id': f'iprm-email-{log_entry.id}',
        'to_email': log_entry.to_email,
        'iprm_user_id': None,
        'template_key': log_entry.template_name,
        'subject': getattr(log_entry, 'subject', None),
        'status': 'sent',
        'sent_at': log_entry.sent_at.isoformat() if log_entry.sent_at else None,
        'trigger': getattr(log_entry, 'trigger', None),
    })


def _lead_payload(lead) -> dict:
    """Заявка з Meta Lead Ads у формі, яку розуміє картка клієнта партнера.

    Три неочевидні речі, кожна з них -- наслідок улаштування приймача.

    **Телефон трьома ключами.** На тому боці два різні резолвери читають
    його з РІЗНИХ полів: пошук ліда -- з ``phone``, пошук клієнта -- з
    ``phone_e164``/``phone_raw``. Payload, що годує лише один із них,
    мовчки не зіставить людину -- ані помилки, ані картки.

    **Сирий номер іде завжди**, навіть коли канонічної форми немає. Ми
    зводимо до E.164 лише українські номери, а в партнера повноцінний
    нормалізатор: те, з чим не впорався слабший, цілком розбирає сильніший.
    Не дублювання даних, а передача роботи туди, де її зроблять краще.

    **`iprm_user_id` завжди відомий**, бо подія народжується ПІСЛЯ
    прив'язки контакту. Для партнера це найсильніший ключ зіставлення --
    сильніший за телефон.
    """
    return {
        'leadgen_id': lead.leadgen_id,
        'created_time': lead.created_time.isoformat() if lead.created_time else None,
        'iprm_user_id': lead.user_id,
        'first_name': lead.first_name,
        'last_name': lead.last_name,
        'email': lead.email,
        # Канонічна форма, якщо є; інакше сирий рядок -- аби резолверу
        # ліда було що читати.
        'phone': lead.phone_e164 or lead.phone_raw,
        'phone_e164': lead.phone_e164,
        'phone_raw': lead.phone_raw,
        'source': {
            'channel': 'meta_lead_ads',
            'platform': lead.platform,
            'form_id': lead.form_id,
            'form_name': lead.form_name,
            'campaign_id': lead.campaign_id,
            'campaign_name': lead.campaign_name,
            'ad_id': lead.ad_id,
        },
        'is_repeat': bool(lead.is_repeat),
        'custom_fields': lead.field_data or {},
    }


def emit_lead_created(lead) -> None:
    """Розповісти партнеру про нову заявку з реклами.

    Викликається З ЧЕРГИ розбору, після успішної прив'язки контакту й
    коміту: подія про заявку, яка ще може відкотитись, -- це подія про те,
    чого не сталося.

    **Тестові заявки не йдуть нікуди.** Lead Ads Testing Tool ллє їх тим
    самим шляхом, що й справжні; пропустити їх у чужу базу означає
    засмітити її картками, яких ніхто не замовляв, і чужими руками.

    Заявка без жодного контакту теж не йде: зіставити її нема за чим, а
    картка з самим лише іменем -- це майбутній дубль на тезці.
    """
    if lead is None or lead.is_test:
        return
    if not (lead.email or lead.phone_e164 or lead.phone_raw):
        return

    emit(LEAD_CREATED, _lead_payload(lead))
