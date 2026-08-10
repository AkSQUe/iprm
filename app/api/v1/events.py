"""Partner API v1 — courses listing & detail.

Endpoint назви (`/events`, `/events/<slug>`) збережено для зворотної
сумісності з MM Medic та іншими партнерами. Джерело даних --
Course + CourseInstance (нова модель).
"""
from datetime import datetime, timezone

from flask import abort, jsonify, make_response, request
from sqlalchemy import and_, func, nulls_last, select
from sqlalchemy.orm import joinedload, selectinload

from app.api.v1 import api_v1_bp
from app.api.v1.auth import require_api_key
from app.api.v1.serializers import (
    API_VERSION,
    pick_representative_instance,
    serialize_event_card,
    serialize_event_detail,
)
from app.extensions import csrf, db, limiter
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration


# 'cancelled' можна ЗАПИТАТИ явно, але його немає в DEFAULT_STATUSES: партнер,
# який будує розклад, мусить показати «Захід скасовано», а не мовчки прибрати
# рядок -- інакше скасування й видалення для нього виглядають однаково. Той,
# хто про це не просив, поведінки не змінює.
ALLOWED_STATUSES = {'published', 'active', 'completed', 'cancelled'}
DEFAULT_STATUSES = ('published', 'active')

MAX_PAGE = 10_000
MAX_PER_PAGE = 100
DEFAULT_PER_PAGE = 50

# Порядок видачі. `start_desc` лишається типовим, бо на нього вже спираються
# наявні споживачі (історія семінарів у виконавчому звіті MM Medic); розклад
# просить `start_asc` явно.
SORT_START_DESC = 'start_desc'
SORT_START_ASC = 'start_asc'
ALLOWED_SORTS = (SORT_START_DESC, SORT_START_ASC)

# Cache-Control: партнер може cache-ити list до 5 хв, detail -- до 2 хв
CACHE_TTL_LIST_SECONDS = 300
CACHE_TTL_DETAIL_SECONDS = 120


def _parse_statuses(status_param):
    """Повертає список валідних статусів або None якщо хоч один невалідний.

    None -> caller поверне 400 Bad Request.
    """
    if not status_param:
        return list(DEFAULT_STATUSES)
    requested = [s.strip() for s in status_param.split(',') if s.strip()]
    if not requested:
        return list(DEFAULT_STATUSES)
    for s in requested:
        if s not in ALLOWED_STATUSES:
            return None
    return requested


def _parse_pagination():
    """(page, per_page, error_message|None)."""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        return None, None, 'page/per_page must be integers'
    if page < 1 or page > MAX_PAGE:
        return None, None, f'page must be in [1, {MAX_PAGE}]'
    if per_page < 1 or per_page > MAX_PER_PAGE:
        return None, None, f'per_page must be in [1, {MAX_PER_PAGE}]'
    return page, per_page, None


def _parse_window():
    """(date_from, date_to, error|None) -- вікно дат для розкладу.

    Приймає ISO-дату (`2026-09-01`) або повний ISO-час. Гола дата в `date_to`
    трактується як КІНЕЦЬ доби: інакше `date_to=2026-09-01` мовчки викидало б
    усі заходи того самого дня, і партнер бачив би порожній вересень.

    `upcoming=1` -- скорочення для `date_from=зараз`; разом із явним
    `date_from` перемагає пізніша з двох меж.
    """
    def parse(raw, end_of_day=False):
        raw = (raw or '').strip()
        if not raw:
            return None, None
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            return None, f'invalid date: {raw!r}; expected ISO-8601'
        if len(raw) == 10 and end_of_day:
            value = value.replace(hour=23, minute=59, second=59, microsecond=999999)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value, None

    date_from, err = parse(request.args.get('date_from'))
    if err:
        return None, None, err
    date_to, err = parse(request.args.get('date_to'), end_of_day=True)
    if err:
        return None, None, err

    if _truthy(request.args.get('upcoming')):
        now = datetime.now(timezone.utc)
        date_from = max(date_from, now) if date_from else now

    if date_from and date_to and date_from > date_to:
        return None, None, 'date_from must not be later than date_to'
    return date_from, date_to, None


def _truthy(raw):
    return (raw or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _ordering(expression, sort):
    """ORDER BY з передбачуваним місцем для проведень без дати.

    Проведення бувають без `start_date` (дата ще не оголошена). Куди їх
    поставить голий ORDER BY -- залежить від СУБД: SQLite кладе NULL першими
    при ASC, PostgreSQL -- останніми. Тобто розклад упорядковувався б
    по-різному на dev і в проді, і партнер отримував би заходи «без дати» на
    чолі списку рівно там, де це найпомітніше.

    `NULLS LAST` в обидві сторони: невизначена дата -- завжди в кінці, бо
    вона не конкурує за увагу з оголошеними.
    """
    ordered = expression.asc() if sort == SORT_START_ASC else expression.desc()
    return nulls_last(ordered)


def _parse_sort():
    """(sort, error|None)."""
    raw = (request.args.get('sort') or SORT_START_DESC).strip().lower()
    if raw not in ALLOWED_SORTS:
        return None, f'invalid sort; allowed: {list(ALLOWED_SORTS)}'
    return raw, None


def _apply_window(query, date_from, date_to):
    """Вікно дат по `CourseInstance.start_date`.

    Проведення без дати (TBD) у вікно НЕ потрапляє: у розкладі йому немає де
    стати, а мовчки чіпляти його до краю діапазону означало б показати захід
    у місяці, до якого він не має стосунку.
    """
    if date_from is not None:
        query = query.filter(CourseInstance.start_date >= date_from)
    if date_to is not None:
        query = query.filter(CourseInstance.start_date <= date_to)
    return query


def _hydrate_reg_counts(instances):
    """Batch COUNT активних реєстрацій; встановлює `_cached_reg_count`."""
    if not instances:
        return
    counts = dict(
        db.session.query(
            EventRegistration.instance_id,
            func.count(EventRegistration.id),
        )
        .filter(
            EventRegistration.instance_id.in_([i.id for i in instances]),
            EventRegistration.status.notin_(['cancelled']),
        )
        .group_by(EventRegistration.instance_id)
        .all()
    )
    for inst in instances:
        inst._cached_reg_count = counts.get(inst.id, 0)


def _course_order_key(statuses, date_from, date_to):
    """Скалярний вираз, за яким курс стає в чергу списку.

    Курс представляє один instance -- найближчий майбутній, а якщо таких немає,
    найсвіжіший минулий. Саме за його датою курс і має стояти в списку.

    Раніше ORDER BY у SQL не було зовсім: `paginate()` брав довільний зріз, а
    сортування вже вибраної сторінки в Python створювало ілюзію хронології --
    усередині сторінки порядок був, але сторінка 2 не продовжувала сторінку 1.
    Для розкладу це означає пропущені й повторені заходи при гортанні.
    """
    def scoped(condition_extra=None):
        conditions = [
            CourseInstance.course_id == Course.id,
            CourseInstance.status.in_(statuses),
        ]
        if date_from is not None:
            conditions.append(CourseInstance.start_date >= date_from)
        if date_to is not None:
            conditions.append(CourseInstance.start_date <= date_to)
        if condition_extra is not None:
            conditions.append(condition_extra)
        return conditions

    now = datetime.now(timezone.utc)
    upcoming = (
        select(func.min(CourseInstance.start_date))
        .where(*scoped(CourseInstance.start_date >= now))
        .correlate(Course)
        .scalar_subquery()
    )
    latest_past = (
        select(func.max(CourseInstance.start_date))
        .where(*scoped())
        .correlate(Course)
        .scalar_subquery()
    )
    return func.coalesce(upcoming, latest_past)


def _cached(response, ttl_seconds):
    """Додає Cache-Control + Vary для CDN/browser кешу."""
    response.headers['Cache-Control'] = f'public, max-age={ttl_seconds}'
    response.headers['Vary'] = 'X-API-Key, Accept-Encoding'
    return response


@api_v1_bp.route('/events', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('60 per minute')
def list_events():
    """List active courses visible to partners (схема -- "event-shape" legacy).

    Query params:
      page (int, default 1, max 10000)
      per_page (int, default 50, max 100)
      status (comma-separated: published,active,completed,cancelled)
      granularity (course|instance, default course)
      date_from / date_to (ISO-8601; гола дата в date_to -- кінець доби)
      upcoming (1|true -- скорочення для date_from=зараз)
      sort (start_desc за замовчуванням | start_asc)

    Невалідний параметр -> 400 Bad Request з полем `error`.
    """
    page, per_page, page_err = _parse_pagination()
    if page_err:
        return jsonify({'error': page_err, 'api_version': API_VERSION}), 400

    date_from, date_to, window_err = _parse_window()
    if window_err:
        return jsonify({'error': window_err, 'api_version': API_VERSION}), 400

    sort, sort_err = _parse_sort()
    if sort_err:
        return jsonify({'error': sort_err, 'api_version': API_VERSION}), 400

    statuses = _parse_statuses(request.args.get('status'))
    if statuses is None:
        return jsonify({
            'error': f'invalid status; allowed: {sorted(ALLOWED_STATUSES)}',
            'api_version': API_VERSION,
        }), 400

    granularity = (request.args.get('granularity') or 'course').strip().lower()
    if granularity not in ('course', 'instance'):
        return jsonify({
            'error': "invalid granularity; allowed: ['course', 'instance']",
            'api_version': API_VERSION,
        }), 400
    if granularity == 'instance':
        return _list_instances(statuses, page, per_page, date_from, date_to, sort)

    matching_instance = [CourseInstance.status.in_(statuses)]
    if date_from is not None:
        matching_instance.append(CourseInstance.start_date >= date_from)
    if date_to is not None:
        matching_instance.append(CourseInstance.start_date <= date_to)

    order_key = _course_order_key(statuses, date_from, date_to)
    order_by = _ordering(order_key, sort)

    query = (
        Course.query
        .options(
            joinedload(Course.trainer),
            selectinload(Course.instances).joinedload(CourseInstance.trainer),
        )
        .filter(Course.is_active.is_(True))
        .filter(Course.instances.any(and_(*matching_instance)))
        # Course.id -- не косметика: без стабільного тайбрейкера курси з
        # однаковою датою можуть мінятись місцями між сторінками, і гортання
        # знову губить рядки.
        .order_by(order_by, Course.id.asc())
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    courses = pagination.items

    # Для кожного курсу обираємо представницький instance, обмежуючи статусами
    # із клієнтського фільтра -- щоб response НЕ містив instance зі статусом,
    # який клієнт не запитував (було -- через fallback на completed).
    picked = {
        c.id: pick_representative_instance(
            c, allowed_statuses=statuses, date_from=date_from, date_to=date_to,
        )
        for c in courses
    }
    # Виключаємо курси без matching representative (edge-case: усі instances у
    # status-ах ми пропустили, але `any(status.in_)` матчнув через draft/cancelled
    # якщо вони є. Захист від такої невідповідності.)
    courses = [c for c in courses if picked[c.id] is not None]

    _hydrate_reg_counts([picked[c.id] for c in courses])
    # Порядок уже заданий у SQL (`_course_order_key`), тож пересортовувати
    # сторінку в Python не можна: це знову дало б хронологію лише всередині
    # сторінки і зламало б `sort=start_desc`.

    body = {
        'api_version': API_VERSION,
        'items': [serialize_event_card(c, picked[c.id]) for c in courses],
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
    }
    return _cached(make_response(jsonify(body)), CACHE_TTL_LIST_SECONDS)


def _list_instances(statuses, page, per_page, date_from, date_to, sort):
    """List events at INSTANCE granularity -- one card per CourseInstance.

    На відміну від покурсового режиму (один представник на курс, орієнтований
    на майбутнє), тут кожен CourseInstance -- окремий елемент. Потрібно
    партнерам (mm-medic) для звітності по минулих/завершених заходах, які в
    покурсовому режимі не видно. Картка та сама (serialize_event_card з явним
    instance); унікальний ключ елемента -- поле `instance_id`.
    """
    order_by = _ordering(CourseInstance.start_date, sort)

    query = _apply_window(
        CourseInstance.query
        .join(Course, CourseInstance.course_id == Course.id)
        .options(
            joinedload(CourseInstance.course).joinedload(Course.trainer),
            joinedload(CourseInstance.trainer),
        )
        .filter(Course.is_active.is_(True))
        .filter(CourseInstance.status.in_(statuses)),
        date_from, date_to,
    ).order_by(order_by, CourseInstance.id.asc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    instances = pagination.items
    _hydrate_reg_counts(instances)

    body = {
        'api_version': API_VERSION,
        'granularity': 'instance',
        'items': [serialize_event_card(i.course, i) for i in instances],
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
    }
    return _cached(make_response(jsonify(body)), CACHE_TTL_LIST_SECONDS)


@api_v1_bp.route('/events/<slug>', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('120 per minute')
def get_event(slug):
    """Detail курсу. 404 -- не існує. 410 -- існував але деактивований."""
    course = (
        Course.query
        .options(
            joinedload(Course.trainer),
            selectinload(Course.instances).joinedload(CourseInstance.trainer),
            selectinload(Course.program_blocks),
        )
        .filter_by(slug=slug)
        .first()
    )
    if not course:
        return jsonify({'error': 'Not Found', 'api_version': API_VERSION}), 404
    if not course.is_active:
        # Partner може прибрати курс у себе з кеша.
        return jsonify({'error': 'Gone', 'api_version': API_VERSION}), 410

    instance = pick_representative_instance(course)
    if instance:
        _hydrate_reg_counts([instance])

    body = serialize_event_detail(course, instance)
    body['api_version'] = API_VERSION
    return _cached(make_response(jsonify(body)), CACHE_TTL_DETAIL_SECONDS)
