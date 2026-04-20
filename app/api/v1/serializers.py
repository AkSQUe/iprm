"""JSON serializers for API v1.

Після міграції на Course+CourseInstance формат відповіді незмінний --
партнерські сайти (MM Medic) продовжують отримувати "event-shape" JSON.
Дані джерела:
  * Контент (title, description, tags, ...) -- з Course
  * Дата/локація/формат -- з представницького CourseInstance
    (найближчий майбутній; якщо немає -- найсвіжіший минулий із дозволених)
  * registration_url -- вказує на new-flow /registration/instance/<id>

Публічний контракт -- `api_version`. Breaking change -> новий major.
"""
from datetime import datetime, timezone

from flask import url_for

from app.utils import ensure_utc

API_VERSION = '1.0'

_DEFAULT_UPCOMING_STATUSES = ('published', 'active')
_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)
_FAR_PAST = datetime.min.replace(tzinfo=timezone.utc)


def _image_url(path: str) -> str | None:
    """Convert stored image path to absolute URL.

    Handles three storage conventions in IPRM:
      1. Absolute URL already -- pass through.
      2. 'static/images/...' or '/static/images/...' -- strip 'static/' prefix
         because url_for('static', ...) adds it; otherwise we get
         '/static/static/images/...'.
      3. 'images/courses/...' or similar -- plain filename relative to static.
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


def _has_upcoming(instance) -> bool:
    """Чи instance планується в майбутньому (published/active + дата >= now)."""
    if not instance:
        return False
    if instance.status not in _DEFAULT_UPCOMING_STATUSES:
        return False
    if instance.start_date is None:
        return True  # TBD -- considered upcoming until date set
    return ensure_utc(instance.start_date) >= datetime.now(timezone.utc)


def pick_representative_instance(course, allowed_statuses=None):
    """Вибрати найрелевантніший instance курсу для API-відповіді.

    Пріоритет: найближчий майбутній (published/active). Fallback --
    найсвіжіший минулий з числа `allowed_statuses` (або 'completed' по
    замовчуванню). None якщо нічого не підходить.

    Args:
        course: Course model (instances мають бути preloaded).
        allowed_statuses: iterable статусів, які дозволено віддавати клієнту.
            Якщо None -- по замовчуванню ('published', 'active', 'completed').
            Фільтр застосовується і до upcoming (гарантія), і до past (fallback).
    """
    if not course.instances:
        return None

    allowed = set(allowed_statuses) if allowed_statuses else {
        'published', 'active', 'completed',
    }
    now = datetime.now(timezone.utc)

    upcoming = [
        i for i in course.instances
        if i.status in _DEFAULT_UPCOMING_STATUSES
        and i.status in allowed
        and (i.start_date is None or ensure_utc(i.start_date) >= now)
    ]
    if upcoming:
        return min(
            upcoming,
            key=lambda i: ensure_utc(i.start_date) or _FAR_FUTURE,
        )

    past = sorted(
        (i for i in course.instances if i.status in allowed),
        key=lambda i: ensure_utc(i.start_date) or _FAR_PAST,
        reverse=True,
    )
    return past[0] if past else None


def serialize_instance(instance) -> dict:
    """Компактна серіалізація одного CourseInstance для API."""
    return {
        'id': instance.id,
        'start_date': instance.start_date.isoformat() if instance.start_date else None,
        'end_date': instance.end_date.isoformat() if instance.end_date else None,
        'event_format': instance.event_format,
        'status': instance.status,
        'location': instance.location,
        'online_link': instance.online_link,
        'price': (
            float(instance.effective_price)
            if instance.effective_price is not None else 0.0
        ),
        'registration_url': _registration_url(instance),
    }


def serialize_event_card(course, instance=None) -> dict:
    """Compact representation для event list (no heavy fields).

    Args:
        course: Course model.
        instance: Optional CourseInstance (pre-picked для N+1 avoidance).
                  If None, `pick_representative_instance` вибере сам.
    """
    if instance is None:
        instance = pick_representative_instance(course)

    effective_price = (
        instance.effective_price if instance
        else (course.base_price or 0)
    )

    return {
        'id': course.id,
        'slug': course.slug,
        'title': course.title,
        'subtitle': course.subtitle,
        'short_description': course.short_description,
        'event_type': course.event_type,
        'event_format': instance.event_format if instance else None,
        'status': instance.status if instance else 'draft',
        'start_date': instance.start_date.isoformat() if instance and instance.start_date else None,
        'end_date': instance.end_date.isoformat() if instance and instance.end_date else None,
        'price': float(effective_price) if effective_price is not None else 0.0,
        'currency': 'UAH',
        'location': instance.location if instance else None,
        'card_image_url': _image_url(course.card_image),
        'hero_image_url': _image_url(course.hero_image),
        'cpd_points': (
            instance.effective_cpd_points if instance
            else course.cpd_points
        ),
        'tags': course.tags or [],
        'is_featured': course.is_featured,
        'max_participants': (
            instance.effective_max_participants if instance
            else course.max_participants
        ),
        'seats_left': _seats_left(instance) if instance else None,
        'registration_url': _registration_url(instance),
        'detail_url': _detail_url(course),
        'trainer': serialize_trainer(
            instance.effective_trainer if instance else course.trainer
        ),
        'instance_id': instance.id if instance else None,
        'has_upcoming': _has_upcoming(instance),
    }


def serialize_event_detail(course, instance=None) -> dict:
    """Full representation для event detail (modal + redirect)."""
    if instance is None:
        instance = pick_representative_instance(course)

    data = serialize_event_card(course, instance)
    data.update({
        'description': course.description,
        'target_audience': course.target_audience or [],
        'speaker_info': course.speaker_info,
        'agenda': course.agenda,
        'faq': course.faq or [],
        'program_blocks': [
            {
                'heading': block.heading,
                'items': block.items or [],
                'sort_order': block.sort_order,
            }
            for block in sorted(course.program_blocks, key=lambda b: b.sort_order or 0)
        ],
        # Всі published/active/completed instances (partner відображає розклад)
        'instances': [
            serialize_instance(i)
            for i in sorted(
                course.instances,
                key=lambda i: ensure_utc(i.start_date) or _FAR_PAST,
            )
            if i.status in ('published', 'active', 'completed')
        ],
    })
    return data


def _seats_left(instance) -> int | None:
    cap = instance.effective_max_participants
    if cap is None:
        return None
    count = getattr(instance, '_cached_reg_count', None)
    if count is None:
        count = instance.registration_count
    return max(0, cap - count)


def _registration_url(instance) -> str | None:
    if not instance:
        return None
    return url_for(
        'registration.register_instance',
        instance_id=instance.id,
        _external=True,
    )


def _detail_url(course) -> str:
    return url_for('courses.course_by_slug', slug=course.slug, _external=True)
