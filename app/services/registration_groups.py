"""Агрегати реєстрацій за курсами й датами -- режим «За заходами».

Сторінка цього режиму складається з ЧИСЕЛ: жодна реєстрація в ORM тут не
гідратується. Рядок учасника коштує батчів (стан тестування, анкета,
сертифікат, незакрита доплата), і платити їх за тисячи рядків, з яких
дивитимуться на десяток, немає за що -- самі рядки приїжджають окремим
маршрутом уже після кліку.
"""
from types import SimpleNamespace

from sqlalchemy import case, func, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.services.seating import occupied_counts


def grouped_page(matched_query, page, per_page, oldest_first=False):
    """Сторінка груп «курс -> дата» з підсумками.

    matched_query -- запит ID реєстрацій, що вже пройшли фільтри сторінки
    (`_apply_registration_filters(db.session.query(EventRegistration.id),
    filters)`). Саме він, а не власний набір умов: заголовок і вміст мусять
    рахуватись з одного джерела, інакше число в шапці обіцяє одне, а
    розгортання дає інше.

    Пагінація -- по КУРСАХ: вага сторінки не має залежати від числа
    реєстрацій під ними.
    """
    matched_ids = select(matched_query.subquery().c.id)
    instance_ids = select(EventRegistration.instance_id).where(
        EventRegistration.id.in_(matched_ids))

    order_col = (func.min(CourseInstance.start_date).asc() if oldest_first
                 else func.max(CourseInstance.start_date).desc())
    courses_stmt = select(CourseInstance.course_id).where(
        CourseInstance.id.in_(instance_ids),
    ).group_by(CourseInstance.course_id).order_by(order_col)
    # db.paginate віддає СКАЛЯРИ, тож у вибірці рівно одна колонка:
    # багатоколонковий select тут мовчки втратив би решту.
    pagination = db.paginate(courses_stmt, page=page, per_page=per_page,
                             error_out=False)
    course_ids = list(pagination.items)
    if not course_ids:
        return [], pagination

    counts = {
        row.instance_id: row
        for row in db.session.query(
            EventRegistration.instance_id.label('instance_id'),
            func.count(EventRegistration.id).label('total'),
            func.count(case((EventRegistration.status == 'confirmed', 1))).label('confirmed'),
            func.count(case((EventRegistration.status == 'pending', 1))).label('pending'),
            func.count(case((EventRegistration.status == 'cancelled', 1))).label('cancelled'),
            func.coalesce(func.sum(EventRegistration.payment_amount), 0).label('amount'),
            func.coalesce(func.sum(case((
                EventRegistration.payment_status == 'paid',
                EventRegistration.payment_amount))), 0).label('paid'),
        ).filter(
            EventRegistration.id.in_(matched_ids),
        ).group_by(EventRegistration.instance_id).all()
    }

    # Проведення гідратуємо -- на відміну від реєстрацій, їх стільки ж,
    # скільки рядків на екрані, а `effective_title` і
    # `effective_max_participants` -- це успадкування від курсу, якого
    # колонковим запитом не відтворити.
    instances = db.session.query(CourseInstance).options(
        joinedload(CourseInstance.course),
    ).filter(
        CourseInstance.course_id.in_(course_ids),
        CourseInstance.id.in_(instance_ids),
    ).all()
    occupied = occupied_counts([inst.id for inst in instances])

    by_course = {}
    for inst in instances:
        row = counts.get(inst.id)
        if row is None:
            continue
        capacity = inst.effective_max_participants
        taken = occupied.get(inst.id, 0)
        by_course.setdefault(inst.course_id, []).append(SimpleNamespace(
            instance=inst,
            total=row.total,
            confirmed=row.confirmed,
            pending=row.pending,
            cancelled=row.cancelled,
            amount=row.amount,
            paid=row.paid,
            due=row.amount - row.paid,
            occupied=taken,
            capacity=capacity,
            overbooked=capacity is not None and taken > capacity,
        ))

    groups = []
    for course_id in course_ids:
        rows = by_course.get(course_id)
        if not rows:
            continue
        # Заходи без дати (TBD) тримаємо скраю: None не порівняти з датою.
        rows.sort(key=lambda r: (r.instance.start_date is None,
                                 r.instance.start_date),
                  reverse=not oldest_first)
        groups.append(SimpleNamespace(
            course=rows[0].instance.course,
            instances=rows,
            total=sum(r.total for r in rows),
            confirmed=sum(r.confirmed for r in rows),
            pending=sum(r.pending for r in rows),
            cancelled=sum(r.cancelled for r in rows),
            amount=sum(r.amount for r in rows),
            paid=sum(r.paid for r in rows),
            due=sum(r.due for r in rows),
        ))
    return groups, pagination
