"""Підбір курсів для крос-селу ("Наступний крок").

Один сервіс на всі точки показу: сторінка курсу, екран підтвердження
реєстрації, екран успішної оплати та гостьовий екран оплати. Логіка добору
має жити в одному місці -- інакше блоки на різних екранах розповзуться (DRY).

Контракт повернення навмисно збігається з course_listing.gather_active_courses:
(courses, upcoming, seats_left, open_ids) -- шаблонні партіали читають ті самі
структури, що й каталог із Головною.
"""
from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.services.course_listing import (
    active_courses,
    capacity_map,
    open_from_capacity,
    upcoming_by_course,
)

# Скільки карток показуємо за замовчуванням -- рівно один рядок сітки.
DEFAULT_LIMIT = 3


def _registered_course_ids(user):
    """Курси, на які користувач уже має активну реєстрацію.

    Пропонувати щойно куплений (або вже куплений раніше) курс -- найгірше,
    що може зробити блок крос-селу. Один запит, без N+1.
    """
    if user is None or not getattr(user, 'is_authenticated', True):
        return set()
    user_id = getattr(user, 'id', None)
    if user_id is None:
        return set()
    rows = (
        db.session.query(CourseInstance.course_id)
        .join(
            EventRegistration,
            EventRegistration.instance_id == CourseInstance.id,
        )
        .filter(
            EventRegistration.user_id == user_id,
            EventRegistration.status.notin_(['cancelled']),
        )
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def recommend_courses(base_course=None, user=None, limit=DEFAULT_LIMIT,
                      exclude_course_ids=()):
    """Курси для блоку рекомендацій.

    Ранжування у два рівні:
      1) спершу курси, на які реально можна записатись (є майбутнє проведення
         з вільними місцями) -- крос-сел без доступної дати марний;
      2) у межах групи -- за кількістю спільних тегів із base_course, далі
         порядок каталогу (закріплені -> sort_order -> назва).

    base_course=None (екрани оплати без прив'язки до курсу) -- лишається
    доступність + порядок каталогу.

    Повертає (courses, upcoming, seats_left, open_ids).
    """
    excluded = set(exclude_course_ids or ())
    if base_course is not None:
        excluded.add(base_course.id)
    excluded |= _registered_course_ids(user)

    candidates = [c for c in active_courses() if c.id not in excluded]
    if not candidates:
        return [], {}, {}, set()

    upcoming = upcoming_by_course(candidates)
    capacity = capacity_map([c.id for c in candidates])
    open_ids = open_from_capacity(capacity)

    base_tags = set((base_course.tags if base_course is not None else None) or [])

    def _rank(item):
        index, course = item
        instances = upcoming.get(course.id, [])
        available = any(i.id in open_ids for i in instances)
        shared = len(base_tags & set(course.tags or []))
        return (0 if available else 1, -shared, index)

    ranked = [course for _, course in sorted(enumerate(candidates), key=_rank)]
    top = ranked[:limit]
    top_ids = {c.id for c in top}
    return (
        top,
        {cid: insts for cid, insts in upcoming.items() if cid in top_ids},
        capacity,
        open_ids,
    )


def recommend_context(base_course=None, user=None, limit=DEFAULT_LIMIT,
                      exclude_course_ids=()):
    """recommend_courses -> готовий dict для render_template(**...).

    Імена ключів (rec_*) навмисно не перетинаються з upcoming_by_course /
    seats_left_map: сторінка курсу вже тримає під тими іменами дані ПОТОЧНОГО
    курсу, і збіг мовчки підмішав би чужі дати й місця в картки блоку.
    """
    courses, upcoming, seats, open_ids = recommend_courses(
        base_course=base_course, user=user, limit=limit,
        exclude_course_ids=exclude_course_ids,
    )
    return {
        'rec_courses': courses,
        'rec_upcoming': upcoming,
        'rec_seats': seats,
        'rec_open_ids': open_ids,
    }
