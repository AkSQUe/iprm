"""JSON serializers for API v1."""
from flask import url_for


def _image_url(path: str) -> str | None:
    """Convert stored image path to absolute URL.

    Handles three storage conventions in IPRM:
      1. Absolute URL already — pass through.
      2. 'static/images/...' or '/static/images/...' — strip 'static/' prefix
         because url_for('static', ...) adds it; otherwise we get
         '/static/static/images/...'.
      3. 'images/courses/...' or similar — plain filename relative to static.
    """
    if not path:
        return None
    if path.startswith(('http://', 'https://')):
        return path
    normalized = path.lstrip('/')
    if normalized.startswith('static/'):
        normalized = normalized[len('static/'):]
    return url_for('static', filename=normalized, _external=True)


def serialize_trainer(trainer) -> dict | None:
    if not trainer:
        return None
    return {
        'slug': trainer.slug,
        'full_name': trainer.full_name,
        'role': trainer.role,
        'photo_url': _image_url(trainer.photo),
    }


def serialize_event_card(event) -> dict:
    """Compact representation for event list (no heavy fields)."""
    return {
        'id': event.id,
        'slug': event.slug,
        'title': event.title,
        'subtitle': event.subtitle,
        'short_description': event.short_description,
        'event_type': event.event_type,
        'event_format': event.event_format,
        'status': event.status,
        'start_date': event.start_date.isoformat() if event.start_date else None,
        'end_date': event.end_date.isoformat() if event.end_date else None,
        'price': float(event.price) if event.price is not None else 0.0,
        'currency': 'UAH',
        'location': event.location,
        'card_image_url': _image_url(event.card_image),
        'hero_image_url': _image_url(event.hero_image),
        'cpd_points': event.cpd_points,
        'tags': event.tags or [],
        'is_featured': event.is_featured,
        'max_participants': event.max_participants,
        'seats_left': _seats_left(event),
        'registration_url': _registration_url(event),
        'detail_url': _detail_url(event),
        'trainer': serialize_trainer(event.trainer),
    }


def serialize_event_detail(event) -> dict:
    """Full representation for event detail (modal + redirect)."""
    data = serialize_event_card(event)
    data.update({
        'description': event.description,
        'target_audience': event.target_audience or [],
        'speaker_info': event.speaker_info,
        'agenda': event.agenda,
        'faq': event.faq or [],
        'trainer': serialize_trainer(event.trainer),
        'program_blocks': [
            {
                'heading': block.heading,
                'items': block.items or [],
                'sort_order': block.sort_order,
            }
            for block in sorted(event.program_blocks, key=lambda b: b.sort_order or 0)
        ],
    })
    return data


def _seats_left(event) -> int | None:
    if event.max_participants is None:
        return None
    count = getattr(event, '_cached_reg_count', None)
    if count is None:
        count = event.registration_count
    return max(0, event.max_participants - count)


def _registration_url(event) -> str:
    return url_for(
        'registration.register',
        event_id=event.id,
        _external=True,
    )


def _detail_url(event) -> str:
    return url_for('courses.course_by_slug', slug=event.slug, _external=True)
