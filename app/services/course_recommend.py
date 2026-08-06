"""Підбір курсів для крос-селу ("Наступний крок").

Один сервіс на всі точки показу: сторінка курсу, екран підтвердження
реєстрації, екран успішної оплати та гостьовий екран оплати. Логіка добору
має жити в одному місці -- інакше блоки на різних екранах розповзуться (DRY).

Підбір двофазний. Ранжування працює на "тонких" рядках (id + теги) і одному
агрегаті доступності, і лише переможці довантажуються з проведеннями й
тарифами. Наївний варіант -- узяти course_listing.active_courses() і
відсортувати -- коштував би завантаження ВСЬОГО каталогу з проведеннями,
тарифами й резервами матеріалів заради трьох карток, причому на
найвідвідуванішій сторінці сайту.

Контракт повернення навмисно збігається з course_listing.gather_active_courses:
(courses, upcoming, seats_left, open_ids) -- шаблонні партіали читають ті самі
структури, що й каталог із Головною.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.services.course_listing import (
    open_from_capacity,
    upcoming_by_course,
    upcoming_capacity,
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


def _load_cards(course_ids):
    """Повні дані курсів для карток -- рівно те, що читає партіал."""
    options = [
        joinedload(Course.card_media),
        selectinload(Course.instances).selectinload(CourseInstance.tariffs),
    ]
    # material_reservations -- backref MM Medic із lazy='selectin'
    # (models/material_reservation.py): без явного noload кожне завантаження
    # проведень тягне ще й резерви матеріалів та їхні позиції, яких картці
    # не треба. getattr -- бо backref зʼявляється лише після конфігурації
    # мапперів, а модуль може бути імпортовано раніше.
    reservations = getattr(CourseInstance, 'material_reservations', None)
    if reservations is not None:
        options.append(selectinload(Course.instances).noload(reservations))
    return Course.query.options(*options).filter(Course.id.in_(course_ids)).all()


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
    empty = ([], {}, {}, set())
    excluded = set(exclude_course_ids or ())
    if base_course is not None:
        excluded.add(base_course.id)
    excluded |= _registered_course_ids(user)

    # Фаза 1 -- ранжування без завантаження самих курсів.
    rows = (
        db.session.query(Course.id, Course.tags)
        .filter(Course.is_active.is_(True))
        .order_by(Course.is_pinned.desc(), Course.sort_order, Course.title)
        .all()
    )
    candidates = [(cid, tags) for cid, tags in rows if cid not in excluded]
    if not candidates:
        return empty

    # Один `now` на обидва обчислення: інакше проведення, що починається
    # рівно зараз, може потрапити в upcoming, але не в мапу місткості.
    now = datetime.now(timezone.utc)
    capacity, open_course_ids = upcoming_capacity(
        [cid for cid, _ in candidates], now=now,
    )
    base_tags = set((base_course.tags if base_course is not None else None) or [])

    def _rank(item):
        index, (course_id, tags) = item
        shared = len(base_tags & set(tags or []))
        return (0 if course_id in open_course_ids else 1, -shared, index)

    ranked = sorted(enumerate(candidates), key=_rank)
    top_ids = [course_id for _, (course_id, _) in ranked][:limit]

    # Фаза 2 -- повні дані лише для відібраних.
    courses = _load_cards(top_ids)
    position = {course_id: i for i, course_id in enumerate(top_ids)}
    courses.sort(key=lambda c: position[c.id])

    upcoming = upcoming_by_course(courses, now=now)
    shown = {inst.id for insts in upcoming.values() for inst in insts}
    seats = {iid: left for iid, left in capacity.items() if iid in shown}
    return courses, upcoming, seats, open_from_capacity(seats)


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
