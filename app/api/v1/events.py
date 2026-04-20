"""Public API v1 — courses listing & detail for partner sites.

Endpoint назви (`/events`, `/events/<slug>`) збережено для зворотної
сумісності з MM Medic та іншими партнерами. Джерело даних --
Course + CourseInstance (нова модель).
"""
from flask import abort, jsonify, request
from sqlalchemy.orm import joinedload, selectinload

from app.api.v1 import api_v1_bp
from app.api.v1.auth import require_api_key
from app.api.v1.serializers import (
    pick_representative_instance,
    serialize_event_card,
    serialize_event_detail,
)
from app.extensions import csrf, db, limiter
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from sqlalchemy import func


@api_v1_bp.route('/events', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('60 per minute')
def list_events():
    """List active courses visible to partners (схема -- "event-shape" legacy).

    Query params:
      page (int, default 1)
      per_page (int, default 50, max 100)
      status (comma-separated: published,active,completed -- статус instance)
    """
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, max(1, request.args.get('per_page', 50, type=int)))
    status_param = request.args.get('status', 'published,active')
    allowed_statuses = {'published', 'active', 'completed'}
    statuses = [s.strip() for s in status_param.split(',') if s.strip() in allowed_statuses]
    if not statuses:
        statuses = ['published', 'active']

    # Показуємо тільки активні курси, у яких є хоча б один instance з бажаним статусом
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

    # Для кожного курсу обираємо представницький instance
    picked = {c.id: pick_representative_instance(c) for c in courses}

    # Batch-fetch registration counts per instance
    instance_ids = [i.id for i in picked.values() if i]
    if instance_ids:
        counts = dict(
            db.session.query(
                EventRegistration.instance_id,
                func.count(EventRegistration.id),
            )
            .filter(
                EventRegistration.instance_id.in_(instance_ids),
                EventRegistration.status.notin_(['cancelled']),
            )
            .group_by(EventRegistration.instance_id)
            .all()
        )
        for instance in picked.values():
            if instance:
                instance._cached_reg_count = counts.get(instance.id, 0)

    # Сортуємо курси по даті представницького instance (найближчі спершу)
    from datetime import datetime, timezone
    from app.utils import ensure_utc
    courses_sorted = sorted(
        courses,
        key=lambda c: (
            ensure_utc(picked[c.id].start_date) if picked[c.id] and picked[c.id].start_date
            else datetime.max.replace(tzinfo=timezone.utc)
        ),
    )

    return jsonify({
        'items': [serialize_event_card(c, picked[c.id]) for c in courses_sorted],
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
    })


@api_v1_bp.route('/events/<slug>', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('120 per minute')
def get_event(slug):
    course = (
        Course.query
        .options(
            joinedload(Course.trainer),
            selectinload(Course.instances).joinedload(CourseInstance.trainer),
            selectinload(Course.program_blocks),
        )
        .filter_by(slug=slug, is_active=True)
        .first()
    )
    if not course:
        abort(404)

    instance = pick_representative_instance(course)
    if instance:
        instance._cached_reg_count = (
            db.session.query(func.count(EventRegistration.id))
            .filter(
                EventRegistration.instance_id == instance.id,
                EventRegistration.status.notin_(['cancelled']),
            )
            .scalar()
            or 0
        )

    return jsonify(serialize_event_detail(course, instance))
