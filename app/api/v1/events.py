"""Partner API v1 — courses listing & detail.

Endpoint назви (`/events`, `/events/<slug>`) збережено для зворотної
сумісності з MM Medic та іншими партнерами. Джерело даних --
Course + CourseInstance (нова модель).
"""
from datetime import datetime, timezone

from flask import abort, jsonify, make_response, request
from sqlalchemy import func
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
from app.utils import ensure_utc


ALLOWED_STATUSES = {'published', 'active', 'completed'}
DEFAULT_STATUSES = ('published', 'active')

MAX_PAGE = 10_000
MAX_PER_PAGE = 100
DEFAULT_PER_PAGE = 50

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


def _sorted_by_start(courses, picked):
    """Сортує курси за датою їх представницького instance (найближчі спершу)."""
    far_future = datetime.max.replace(tzinfo=timezone.utc)

    def key(course):
        inst = picked.get(course.id)
        if inst and inst.start_date:
            return ensure_utc(inst.start_date) or far_future
        return far_future

    return sorted(courses, key=key)


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
      status (comma-separated: published,active,completed -- статус instance)

    Невалідний параметр -> 400 Bad Request з полем `error`.
    """
    page, per_page, page_err = _parse_pagination()
    if page_err:
        return jsonify({'error': page_err, 'api_version': API_VERSION}), 400

    statuses = _parse_statuses(request.args.get('status'))
    if statuses is None:
        return jsonify({
            'error': f'invalid status; allowed: {sorted(ALLOWED_STATUSES)}',
            'api_version': API_VERSION,
        }), 400

    query = (
        Course.query
        .options(
            joinedload(Course.trainer),
            selectinload(Course.instances).joinedload(CourseInstance.trainer),
        )
        .filter(Course.is_active.is_(True))
        .filter(Course.instances.any(CourseInstance.status.in_(statuses)))
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    courses = pagination.items

    # Для кожного курсу обираємо представницький instance, обмежуючи статусами
    # із клієнтського фільтра -- щоб response НЕ містив instance зі статусом,
    # який клієнт не запитував (було -- через fallback на completed).
    picked = {
        c.id: pick_representative_instance(c, allowed_statuses=statuses)
        for c in courses
    }
    # Виключаємо курси без matching representative (edge-case: усі instances у
    # status-ах ми пропустили, але `any(status.in_)` матчнув через draft/cancelled
    # якщо вони є. Захист від такої невідповідності.)
    courses = [c for c in courses if picked[c.id] is not None]

    _hydrate_reg_counts([picked[c.id] for c in courses])
    courses_sorted = _sorted_by_start(courses, picked)

    body = {
        'api_version': API_VERSION,
        'items': [serialize_event_card(c, picked[c.id]) for c in courses_sorted],
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
