"""Локальний життєвий цикл заявки тренера на витратні матеріали.

Заявка -- це той самий `MaterialReservation`, що дозріває: три локальні
стани (`draft` -> `pending_review` -> погоджено) стоять ПЕРЕД наявним
`submitted`, з якого починається розмова з MM Medic.

Межа з `material_reservation_service` навмисна. Там -- усе, що стосується
партнера: підпис, ретраї, дзеркалення відповіді, звірка. Тут -- лише
переходи, які нікуди не летять. `approve()` -- єдина точка, де одне
викликає друге, і вона делегує наявному `submit_request()`, а не пише
другий його варіант.
"""
import logging
from datetime import datetime, timezone

from app.extensions import db
from app.models.material_reservation import (
    MaterialReservation,
    MaterialReservationItem,
    MaterialReservationOrigin,
    MaterialReservationStatus,
)
from app.services import material_reservation_service as mrs

logger = logging.getLogger(__name__)

# Стани, з яких тренер може подати. `returned` тут разом із `draft`: заявку
# повернули саме для того, щоб він виправив і надіслав знову.
_SUBMITTABLE = (MaterialReservationStatus.DRAFT,
                MaterialReservationStatus.RETURNED)

# Стани, у яких відповідальний ухвалює рішення.
_REVIEWABLE = (MaterialReservationStatus.PENDING_REVIEW,)


class RequestTransitionError(Exception):
    """Перехід, якого поточний стан не дозволяє.

    Окремий тип, а не ValueError: роути ловлять саме його і показують текст
    людині, тоді як ValueError з глибини ORM має лишитись помилкою 500.
    Той самий патерн, що `ProposalTransitionError` у trainer_cabinet.py.
    """


def get_or_create_draft(instance, user) -> MaterialReservation:
    """Заявка цього заходу; якщо її ще немає -- нова чернетка.

    Рядок один на захід (`external_ref` унікальний), тож повторний виклик
    повертає ту саму заявку, а не плодить другу. `created_by_id`
    проставляється лише при створенні: якщо заявку колись завів адмін і
    тренер відкрив її пізніше, авторство не переписується під тренера.
    """
    reservation = mrs.get_reservation(instance.id)
    if reservation is not None:
        return reservation
    reservation = MaterialReservation(
        instance_id=instance.id,
        external_ref=mrs.external_ref_for(instance.id),
        status=MaterialReservationStatus.DRAFT,
        origin=MaterialReservationOrigin.TRAINER_CABINET,
        created_by_id=getattr(user, 'id', None),
    )
    db.session.add(reservation)
    db.session.commit()
    return reservation


def save_items(reservation, items) -> None:
    """Переписати перелік заявки з того, що надіслала форма.

    `items` -- список dict'ів {sku, name, image_url, quantity}. Кількість
    лягає в `quantity_requested` («скільки просив тренер»), `quantity_reserved`
    лишається нулем: утримання з'являється лише після погодження на MM Medic.

    Рядки, яких у `items` немає, ВИДАЛЯЄМО, а наявні оновлюємо на місці -- у
    `material_reservation_items` є unique (reservation_id, sku), і видалення
    з наступною вставкою того самого sku в одній транзакції дало б
    IntegrityError на порядку flush'ів.
    """
    incoming = {}
    for raw in items or []:
        sku = (raw.get('sku') or '').strip()
        quantity = raw.get('quantity')
        if not sku or not isinstance(quantity, int) or quantity <= 0:
            continue
        incoming[sku] = raw

    existing = {item.sku: item for item in reservation.items}

    for sku, item in existing.items():
        if sku not in incoming:
            reservation.items.remove(item)

    for sku, raw in incoming.items():
        item = existing.get(sku)
        if item is None:
            item = MaterialReservationItem(sku=sku, quantity_reserved=0)
            reservation.items.append(item)
        item.name = mrs.trim(raw.get('name'), 255)
        item.image_url = mrs.trim(raw.get('image_url'), 500)
        item.quantity_requested = raw['quantity']

    db.session.commit()


def is_editable_by_trainer(reservation) -> bool:
    """Чи може тренер зараз правити цю заявку.

    None -- заявки ще немає, тобто форма порожня й редагована.
    """
    if reservation is None:
        return True
    return reservation.status in _SUBMITTABLE


def submit(reservation, user) -> MaterialReservation:
    """Тренер надіслав заявку на перевірку. Нікуди не летить -- лише статус."""
    if reservation.status not in _SUBMITTABLE:
        raise RequestTransitionError(
            'Надіслати можна лише чернетку або повернену заявку')
    if not any((item.quantity_requested or 0) > 0 for item in reservation.items):
        raise RequestTransitionError('Заявка порожня: додайте хоча б одну позицію')

    reservation.status = MaterialReservationStatus.PENDING_REVIEW
    reservation.origin = MaterialReservationOrigin.TRAINER_CABINET
    reservation.trainer_submitted_at = datetime.now(timezone.utc)
    # Коментар стосувався ПОПЕРЕДНЬОЇ версії; це надсилання його виправляє.
    reservation.review_comment = None
    reservation.reviewed_at = None
    reservation.reviewed_by_id = None
    if getattr(user, 'id', None) is not None:
        reservation.created_by_id = user.id
    db.session.commit()
    return reservation


def _decide(reservation, status, comment, user, empty_message):
    """Спільне тіло «повернути» і «відхилити»: обидва потребують причини."""
    if reservation.status not in _REVIEWABLE:
        raise RequestTransitionError('Рішення можна ухвалити лише щодо заявки на перевірці')
    text = (comment or '').strip()
    if not text:
        raise RequestTransitionError(empty_message)

    reservation.status = status
    reservation.review_comment = text
    reservation.reviewed_at = datetime.now(timezone.utc)
    reservation.reviewed_by_id = getattr(user, 'id', None)
    db.session.commit()
    return reservation


def return_to_trainer(reservation, comment, user) -> MaterialReservation:
    return _decide(reservation, MaterialReservationStatus.RETURNED, comment, user,
                   'Вкажіть, що саме тренеру треба виправити')


def reject(reservation, comment, user) -> MaterialReservation:
    return _decide(reservation, MaterialReservationStatus.REJECTED, comment, user,
                   'Вкажіть причину відхилення')


def approve(instance, reservation):
    """Погодити й надіслати на MM Medic. Повертає (ok, result).

    Гейт на статус стоїть ПЕРЕД викликом партнера і є єдиним запобіжником
    від подвійного надсилання, коли двоє відповідальних тиснуть кнопку
    одночасно: перший переводить рядок у `submitted`, другий уже не проходить
    перевірку й отримує помилку замість другого документа.

    При збої партнера статус НЕ чіпаємо: заявка лишається на перевірці, і
    кнопку можна натиснути ще раз. Стан «начебто погодили, а насправді не
    пішло» тут неможливий саме тому, що статус рухає `submit_request()`, а
    не ця функція.
    """
    if reservation.status not in _REVIEWABLE:
        raise RequestTransitionError('Погодити можна лише заявку на перевірці')

    items = [{'sku': item.sku, 'quantity': item.quantity_requested}
             for item in reservation.items
             if (item.quantity_requested or 0) > 0]
    if not items:
        raise RequestTransitionError('Заявка порожня: погоджувати нічого')

    reviewer_id = mrs._submitter_id()
    ok, result, _reservation = mrs.submit_request(instance, items)
    if not ok:
        logger.warning('Не вдалося надіслати заявку %s на MM Medic',
                       reservation.external_ref)
        return False, result

    reservation.reviewed_at = datetime.now(timezone.utc)
    reservation.reviewed_by_id = reviewer_id
    db.session.commit()
    return True, result


def pending_review_count() -> int:
    """Скільки заявок чекає перевірки -- для лічильника в сайдбарі."""
    return (MaterialReservation.query
            .filter(MaterialReservation.status
                    == MaterialReservationStatus.PENDING_REVIEW)
            .count())
