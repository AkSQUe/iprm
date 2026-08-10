"""Спільна логіка публічного лістингу курсів (каталог + Головна).

Виносить збір активних курсів, їхніх майбутніх проведень і мапи місткості,
щоб не дублювати цей код у courses.course_list і main.index (DRY) і не
імпортувати приватні хелпери з блупринта в блупринт (ARCH).
"""
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.utils import ensure_utc


def capacity_map(course_ids):
    """{CourseInstance.id: seats_left} для published/active проведень.

    seats_left == None -> місткість не задана (необмежено). Інакше -- вільні
    місця (>= 0). Один агрегатний запит замість N+1.
    """
    if not course_ids:
        return {}
    rows = (
        db.session.query(
            CourseInstance.id,
            CourseInstance.max_participants,
            Course.max_participants.label('course_max'),
            func.count(EventRegistration.id).label('active_count'),
        )
        .join(Course, Course.id == CourseInstance.course_id)
        .outerjoin(
            EventRegistration,
            db.and_(
                EventRegistration.instance_id == CourseInstance.id,
                EventRegistration.status.notin_(['cancelled']),
            ),
        )
        .filter(
            CourseInstance.course_id.in_(course_ids),
            CourseInstance.status.in_(('published', 'active')),
        )
        .group_by(CourseInstance.id, CourseInstance.max_participants, Course.max_participants)
        .all()
    )
    capacity = {}
    for inst_id, inst_max, course_max, active_count in rows:
        cap = inst_max if inst_max is not None else course_max
        capacity[inst_id] = None if cap is None else max(cap - active_count, 0)
    return capacity


def open_from_capacity(capacity):
    """Множина id проведень, відкритих для реєстрації (є вільні місця)."""
    return {i for i, left in capacity.items() if left is None or left > 0}


def upcoming_capacity(course_ids=None, now=None):
    """Місткість МАЙБУТНІХ проведень: ({inst_id: seats_left}, {course_id}).

    Відрізняється від capacity_map тим, що відкидає минулі дати й заразом
    віддає множину курсів, куди ще можна записатись. Це дозволяє ранжувати
    каталог за доступністю ОДНИМ запитом, не завантажуючи самі проведення
    (див. services.course_recommend).
    """
    now = now or datetime.now(timezone.utc)
    query = (
        db.session.query(
            CourseInstance.course_id,
            CourseInstance.id,
            CourseInstance.max_participants,
            Course.max_participants.label('course_max'),
            func.count(EventRegistration.id).label('active_count'),
        )
        .join(Course, Course.id == CourseInstance.course_id)
        .outerjoin(
            EventRegistration,
            db.and_(
                EventRegistration.instance_id == CourseInstance.id,
                EventRegistration.status.notin_(['cancelled']),
            ),
        )
        .filter(
            CourseInstance.status.in_(('published', 'active')),
            db.or_(
                CourseInstance.start_date.is_(None),
                CourseInstance.start_date >= now,
            ),
        )
        .group_by(
            CourseInstance.course_id, CourseInstance.id,
            CourseInstance.max_participants, Course.max_participants,
        )
    )
    if course_ids is not None:
        if not course_ids:
            return {}, set()
        query = query.filter(CourseInstance.course_id.in_(course_ids))

    capacity, open_courses = {}, set()
    for course_id, inst_id, inst_max, course_max, active_count in query.all():
        cap = inst_max if inst_max is not None else course_max
        left = None if cap is None else max(cap - active_count, 0)
        capacity[inst_id] = left
        if left is None or left > 0:
            open_courses.add(course_id)
    return capacity, open_courses


def active_courses(featured_first=False):
    """Активні курси з підвантаженими тренером/проведеннями/тарифами.

    featured_first=True -- рекомендовані вище (Головна); інакше порядок
    каталогу (pinned -> sort_order -> title).
    """
    order = [Course.is_pinned.desc()]
    if featured_first:
        order.append(Course.is_featured.desc())
    order += [Course.sort_order, Course.title]
    return Course.query.options(
        joinedload(Course.trainer),
        # card_media -- джерело course.card_src у кожній картці лістингу;
        # без цього joinedload картки дають N+1 на медіа-реєстр.
        joinedload(Course.card_media),
        selectinload(Course.instances).joinedload(CourseInstance.trainer),
        selectinload(Course.instances).selectinload(CourseInstance.tariffs),
    ).filter(Course.is_active.is_(True)).order_by(*order).all()


def upcoming_by_course(courses, now=None):
    """{course.id: [майбутні published/active проведення, найближчі першими]}."""
    now = now or datetime.now(timezone.utc)
    _far = datetime.max.replace(tzinfo=timezone.utc)
    return {
        c.id: sorted(
            [i for i in c.instances
             if i.status in ('published', 'active')
             and (i.start_date is None or ensure_utc(i.start_date) >= now)],
            key=lambda i: ensure_utc(i.start_date) or _far,
        )
        for c in courses
    }


def order_by_nearest(courses, upcoming):
    """Порядок каталогу за датою: найближчі проведення вище.

    Закріплені (is_pinned) лишаються зверху у порядку каталогу -- дата на них
    не впливає. Курси без майбутніх проведень ідуть у кінець, зберігаючи
    вихідний порядок (sort_order -> title).
    """
    _far = datetime.max.replace(tzinfo=timezone.utc)

    def sort_key(item):
        idx, course = item
        insts = upcoming.get(course.id) or []
        start = ensure_utc(insts[0].start_date) if insts and insts[0].start_date else None
        if course.is_pinned:
            return (0, _far, idx)
        return (1 if start else 2, start or _far, idx)

    return [course for _, course in sorted(enumerate(courses), key=sort_key)]


def gather_active_courses(featured_first=False):
    """Зібрати все для лістингу: (courses, upcoming_by_course, capacity, open_ids)."""
    courses = active_courses(featured_first=featured_first)
    ubc = upcoming_by_course(courses)
    cap = capacity_map([c.id for c in courses])
    return courses, ubc, cap, open_from_capacity(cap)
