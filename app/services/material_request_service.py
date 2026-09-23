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

from flask_babel import gettext as _

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

# Межі одного рядка форми заявки -- і в кабінеті тренера, і на погодженні в
# адмінці. Кількість лягає в Integer (int4 на Postgres): без верхньої межі
# 11-значне число давало DataError на commit і 500, а SQLite у тестах цього
# не бачить. 10000 -- з великим запасом понад будь-який захід.
MAX_QUANTITY = 10000
MAX_ROWS = 200
_SKU_MAX_LEN = 100  # material_reservation_items.sku -- String(100)


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
        # `or item.*` -- не перезаписувати порожнім. Той самий фолбек, що
        # `apply_items()` у material_reservation_service.py: викликач може
        # надіслати лише {sku, quantity} (саме так робить погодження в
        # адмінці -- форма таблиці кількостей не несе ні назви, ні фото),
        # і без фолбека другий-третій виклик `save_items` на той самий
        # рядок стирав би снапшот назви/зображення, який існує рівно на
        # випадок, якщо товар потім зникне з каталогу MM Medic.
        item.name = mrs.trim(raw.get('name'), 255) or item.name
        item.image_url = mrs.trim(raw.get('image_url'), 500) or item.image_url
        item.quantity_requested = raw['quantity']

    db.session.commit()


def parse_form_rows(skus, quantities):
    """Паралельні списки sku[]/quantity[] з форми -> [{sku, quantity}].

    Спільний для кабінету тренера й погодження в адмінці: обидва приймають ту
    саму форму рядків, і правила не мають розходитись. Порожня, нечислова
    чи нульова кількість -- це прибраний рядок, а не помилка (так працює
    «Прибрати»). А от кількість понад MAX_QUANTITY і забагато рядків --
    помилка введення, про яку треба сказати: мовчки обрізане число -- уже
    інша заявка.
    """
    rows = []
    for sku, raw in zip(skus, quantities):
        sku = (sku or '').strip()
        raw = (raw or '').strip()
        if not sku or not raw or len(sku) > _SKU_MAX_LEN:
            continue
        try:
            quantity = int(float(raw.replace(',', '.')))
        except (ValueError, OverflowError):
            continue
        if quantity <= 0:
            continue
        if quantity > MAX_QUANTITY:
            raise RequestTransitionError(
                _('Кількість не може перевищувати %(max)s', max=MAX_QUANTITY))
        rows.append({'sku': sku, 'quantity': quantity})
    if len(rows) > MAX_ROWS:
        raise RequestTransitionError(
            _('Забагато позицій у заявці: не більше %(max)s', max=MAX_ROWS))
    return rows


def known_products(instance, reservation):
    """Звідки сервер знає, що це за позиція: {sku: {'name', 'image_url'}}.

    Назву й фото НЕ беремо з форми. Форму заповнює тренер, а бачать ці
    підписи відповідальні -- в адмінці й у листі -- і саме за ними вирішують,
    що погодити. Підпис із прихованого поля дозволяв показати рецензенту
    «шприци» під артикулом голок: погодили б шприци, склад відвантажив би
    голки.

    Пріоритет -- від найсвіжішого джерела: каталог MM Medic, потім снапшот
    у самій заявці, потім снапшот комплекту. Каталог, що мовчить, --
    звичайний стан (див. `catalog_for_trainer`): тоді відомі лише комплект і
    вже збережені рядки, і заявку з них усе одно можна подати.
    """
    known = {}
    for kit in mrs.kits_for_instance(instance):
        for item in kit.items:
            known.setdefault(item.sku, {'name': item.name_snapshot,
                                        'image_url': None})
    for item in (reservation.items if reservation is not None else []):
        known[item.sku] = {'name': item.name, 'image_url': item.image_url}
    # Каталог тут -- лише збагачення й розширення відомого, не умова роботи:
    # збої мережі `get_catalog` і так повертає як `error`, а несподіваний
    # виняток не має блокувати погодження заявки, чиї рядки вже відомі.
    try:
        catalog, error, _stale = mrs.get_catalog()
    except Exception:
        logger.exception('Каталог MM Medic недоступний для перевірки заявки, захід %s',
                         instance.id)
        catalog, error = [], 'catalog failed'
    if not error:
        for raw in catalog or []:
            sku = raw.get('sku')
            if sku:
                # Каталог віддає фото під ключем `image` (як і скрізь у
                # material_reservation_service), а не `image_url`.
                known[sku] = {'name': raw.get('name'),
                              'image_url': raw.get('image')}
    return known


def resolve_rows(instance, reservation, rows):
    """[{sku, quantity}] з форми -> ([рядки з назвою й фото від сервера], відкинуті).

    Межа довіри стоїть тут, на вході: рядок, чий артикул сервер не знає, у
    заявку не потрапляє. Відкинуті артикули повертаються, щоб роут сказав про
    них людині, а не загубив мовчки.
    """
    known = known_products(instance, reservation)
    items, dropped = [], []
    for row in rows:
        product = known.get(row['sku'])
        if product is None:
            dropped.append(row['sku'])
            continue
        items.append({'sku': row['sku'], 'quantity': row['quantity'],
                      'name': product['name'], 'image_url': product['image_url']})
    if dropped:
        logger.warning('Заявка на матеріали, захід %s: відкинуто невідомі артикули %s',
                       instance.id, dropped)
    return items, dropped


def is_editable_by_trainer(reservation) -> bool:
    """Чи може тренер зараз правити цю заявку.

    None -- заявки ще немає, тобто форма порожня й редагована.
    """
    if reservation is None:
        return True
    return reservation.status in _SUBMITTABLE


def submit(reservation, user) -> MaterialReservation:
    """Тренер надіслав заявку на перевірку. Нікуди не летить -- лише статус."""
    # Тексти перекладні: їх читає тренер у кабінеті (flash із роуту), а
    # кабінет -- перекладний. Решта відмов цього модуля адресована адмінці
    # й лишається українською.
    if reservation.status not in _SUBMITTABLE:
        raise RequestTransitionError(
            _('Надіслати можна лише чернетку або повернену заявку'))
    if not any((item.quantity_requested or 0) > 0 for item in reservation.items):
        raise RequestTransitionError(_('Заявка порожня: додайте хоча б одну позицію'))

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


def approve(instance, reservation, edits=None):
    """Погодити й надіслати на MM Medic. Повертає (ok, result).

    `edits` -- правки кількостей від відповідального (ті самі dict'и, що
    приймає `save_items`). Лягають у заявку ЛИШЕ ПІСЛЯ гейту статусу: доти
    роут писав їх до перевірки, і застаріла вкладка переписувала кількості
    (і видаляла рядки) вже погодженої заявки, а відмова приходила потім.

    `exists` від MM Medic (документ із цим ref уже відкритий) -- не успіх:
    перевірений перелік партнер НЕ застосував. Статус рухає сам
    `submit_request()` (дзеркало мусить відповідати живому документу),
    але `reviewed_*` тут не пишемо -- рішення цього виклику нічого не
    змінило, і в гонці двох погоджень перезаписало б того, хто встиг першим.
    Відрізнити випадок викликач може через `mrs.document_already_open()`.

    Гейт на статус стоїть ПЕРЕД викликом партнера й ловить повторне
    натискання в межах одного запиту чи одного обʼєкта в пам'яті: щойно
    статус став `submitted`, друга спроба на ТОМУ Ж обʼєкті вже не проходить
    перевірку. Від СПРАВЖНІХ одночасних запитів -- дві окремі сесії БД, що
    обидві встигли прочитати `pending_review` до того, як перша закомітила
    (TOCTOU: тут немає ні `SELECT ... FOR UPDATE`, ні оптимістичного локу) --
    цей гейт НЕ захищає: обидві пройдуть перевірку й обидві підуть у
    `client.submit_request()`. Від дубля документа в такому випадку рятує не
    цей гейт, а ідемпотентність MM Medic за детермінованим `external_ref`
    (docstring `submit_request()` у material_reservation_service.py: повторне
    подання на вже відкритий документ повертає його як є, без змін). Саме
    тому локальний лок тут навмисно не додається.

    При збої партнера статус НЕ чіпаємо: заявка лишається на перевірці, і
    кнопку можна натиснути ще раз. Стан «начебто погодили, а насправді не
    пішло» тут неможливий саме тому, що статус рухає `submit_request()`, а
    не ця функція.
    """
    if reservation.status not in _REVIEWABLE:
        raise RequestTransitionError('Погодити можна лише заявку на перевірці')
    if edits is not None:
        # `is not None`, а не правдивість: порожній список -- це
        # відповідальний, що очистив усі кількості, а не «правок немає». Доти
        # `if edits:` пропускав його, і на склад мовчки йшов початковий
        # перелік тренера. Відмова -- ДО запису: `save_items([])` устиг би
        # стерти рядки заявки, а відмова прийшла б уже потім.
        if not edits:
            raise RequestTransitionError(
                'Усі кількості порожні -- погоджувати нічого. '
                'Якщо матеріали не потрібні, відхиліть заявку.')
        save_items(reservation, edits)

    items = [{'sku': item.sku, 'quantity': item.quantity_requested}
             for item in reservation.items
             if (item.quantity_requested or 0) > 0]
    if not items:
        raise RequestTransitionError('Заявка порожня: погоджувати нічого')

    # Автор заявки -- тренер. `submit_request()` пише в `created_by_id` того,
    # хто натиснув кнопку: для легасі-каналу адмінки це правильно (там автор
    # і є адмін), тож сам сервіс не чіпаємо, а відновлюємо автора тут. Без
    # цього лист «заявку прийнято» (адресат -- `created_by`) ішов адміну.
    author_id = reservation.created_by_id
    reviewer_id = mrs._submitter_id()
    ok, result, _reservation = mrs.submit_request(instance, items)
    if not ok:
        logger.warning('Не вдалося надіслати заявку %s на MM Medic',
                       reservation.external_ref)
        return False, result

    if author_id is not None:
        reservation.created_by_id = author_id
    if not mrs.document_already_open(result):
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


def catalog_for_trainer(search=None):
    """Каталог MM Medic у вигляді, придатному для очей тренера.

    Повертає (items, unavailable). `items` -- лише sku, назва й зображення:
    залишки, ціни й min_stock не ховаються стилями, а НЕ НАДСИЛАЮТЬСЯ. Ціни
    MM Medic -- закупівельні, і зовнішній людині їх знати не треба.

    `unavailable=True` -- партнер мовчить. Це не помилка сторінки: форма
    відкривається з локального комплекту й працює на відправку, недоступним
    стає лише пошук.
    """
    items, error, _stale = mrs.get_catalog(search=search)
    if error:
        return [], True
    return [
        {'sku': raw.get('sku'),
         'name': raw.get('name'),
         # Каталог MM Medic віддає фото під `image`. Доти тут читався
         # `image_url`, якого в каталозі немає, -- тренер ніколи не бачив
         # фото товару, а тест мокав каталог тим самим хибним ключем.
         'image_url': raw.get('image')}
        for raw in (items or [])
        if raw.get('sku')
    ], False


def prefill_rows(instance):
    """Рядки, якими відкривається порожня заявка: стандартний комплект курсу.

    `kits_for_instance` віддає курсові комплекти І універсальні
    (`course_id IS NULL`). Беремо позиції з усіх активних, складаючи
    кількості на однаковий sku: два комплекти, що обидва містять серветки,
    мають дати одну позицію, а не дві.
    """
    merged = {}
    for kit in mrs.kits_for_instance(instance):
        for item in kit.items:
            row = merged.setdefault(item.sku, {
                'sku': item.sku, 'name': item.name_snapshot,
                'image_url': None, 'quantity': 0,
            })
            row['quantity'] += item.quantity or 0
    return [row for row in merged.values() if row['quantity'] > 0]


def rows_for_form(instance, reservation):
    """Що показати у формі: збережена заявка, якщо вона є, інакше префіл."""
    if reservation is not None and reservation.items:
        return [{'sku': item.sku, 'name': item.name,
                 'image_url': item.image_url,
                 'quantity': item.quantity_requested or 0}
                for item in reservation.items]
    return prefill_rows(instance)
