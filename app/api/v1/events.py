"""Public API v1 — events listing & detail for partner sites."""
from flask import abort, jsonify, request
from sqlalchemy.orm import joinedload, selectinload

from app.api.v1 import api_v1_bp
from app.api.v1.auth import require_api_key
from app.api.v1.serializers import serialize_event_card, serialize_event_detail
from app.extensions import csrf, db, limiter
from app.models.event import Event
from app.models.registration import EventRegistration
from sqlalchemy import func


@api_v1_bp.route('/events', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('60 per minute')
def list_events():
    """List published/active events visible to partners.

    Query params:
      page (int, default 1)
      per_page (int, default 50, max 100)
      status (comma-separated: published,active,completed — default: published,active)
    """
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, max(1, request.args.get('per_page', 50, type=int)))
    status_param = request.args.get('status', 'published,active')
    allowed_statuses = {'published', 'active', 'completed'}
    statuses = [s.strip() for s in status_param.split(',') if s.strip() in allowed_statuses]
    if not statuses:
        statuses = ['published', 'active']

    query = (
        Event.query.options(joinedload(Event.trainer))
        .filter(Event.is_active.is_(True), Event.status.in_(statuses))
        .order_by(Event.start_date.asc().nulls_last())
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    events = pagination.items

    # Batch-fetch registration counts to avoid N+1.
    if events:
        counts = dict(
            db.session.query(
                EventRegistration.event_id,
                func.count(EventRegistration.id),
            )
            .filter(
                EventRegistration.event_id.in_([e.id for e in events]),
                EventRegistration.status.notin_(['cancelled']),
            )
            .group_by(EventRegistration.event_id)
            .all()
        )
        for ev in events:
            ev._cached_reg_count = counts.get(ev.id, 0)

    return jsonify({
        'items': [serialize_event_card(e) for e in events],
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
    event = (
        Event.query.options(
            joinedload(Event.trainer),
            selectinload(Event.program_blocks),
        )
        .filter_by(slug=slug, is_active=True)
        .first()
    )
    if not event or event.status not in {'published', 'active', 'completed'}:
        abort(404)

    event._cached_reg_count = (
        db.session.query(func.count(EventRegistration.id))
        .filter(
            EventRegistration.event_id == event.id,
            EventRegistration.status.notin_(['cancelled']),
        )
        .scalar()
        or 0
    )

    return jsonify(serialize_event_detail(event))
