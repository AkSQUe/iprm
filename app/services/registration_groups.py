"""Агрегати реєстрацій за курсами й датами -- режим «За заходами».

Сторінка цього режиму складається з ЧИСЕЛ: жодна реєстрація в ORM тут не
гідратується. Рядок учасника коштує батчів (стан тестування, анкета,
сертифікат, незакрита доплата), і платити їх за тисячи рядків, з яких
дивитимуться на десяток, немає за що -- самі рядки приїжджають окремим
маршрутом уже після кліку.
"""
from types import SimpleNamespace

from sqlalchemy import and_, case, func, nullslast, select
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

    # nullslast -- явно, в обидві гілки: без нього PostgreSQL дає DESC ->
    # NULLS FIRST, і курс без жодної дати став би ПЕРШИМ у типовому перегляді
    # -- рівно те, що вже визнано неприйнятним для дат УСЕРЕДИНІ курсу нижче.
    # SQLite такого нахилу не має, тож без цього тест на цій БД пройшов би, а
    # прод -- ні.
    order_col = (nullslast(func.min(CourseInstance.start_date).asc()) if oldest_first
                 else nullslast(func.max(CourseInstance.start_date).desc()))
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
            # amount_active/paid_active -- ті самі суми, але БЕЗ скасованих:
            # борг рахується тільки від них (нижче, `due`). `amount`/`paid`
            # лишаються по всьому зрізу -- гроші, що реально надійшли по
            # реєстрації, яку потім скасували, нікуди не діваються, і сторінка
            # має показувати їх. Тому `amount - paid != due`, і це навмисно:
            # хтось інший це «полагодить», якщо не буде цього коментаря.
            func.coalesce(func.sum(case((
                EventRegistration.status != 'cancelled',
                EventRegistration.payment_amount))), 0).label('amount_active'),
            func.coalesce(func.sum(case((
                and_(EventRegistration.status != 'cancelled',
                     EventRegistration.payment_status == 'paid'),
                EventRegistration.payment_amount))), 0).label('paid_active'),
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
            # Скасована реєстрація не рахується в борг (`amount_active` /
            # `paid_active` -- див. коментар у запиті вище).
            due=row.amount_active - row.paid_active,
            occupied=taken,
            capacity=capacity,
            overbooked=capacity is not None and taken > capacity,
        ))

    groups = []
    for course_id in course_ids:
        rows = by_course.get(course_id)
        if not rows:
            continue
        # Заходи без дати (TBD) тримаємо в кінці за БУДЬ-ЯКОГО напрямку:
        # спільний ключ із прапорцем `is None` перевертався разом зі
        # списком, і в типовому "новіші зверху" TBD опинявся першим.
        dated = [r for r in rows if r.instance.start_date is not None]
        undated = [r for r in rows if r.instance.start_date is None]
        dated.sort(key=lambda r: r.instance.start_date, reverse=not oldest_first)
        rows = dated + undated
        groups.append(SimpleNamespace(
            course=rows[0].instance.course,
            instances=rows,
            total=sum(r.total for r in rows),
            confirmed=sum(r.confirmed for r in rows),
            pending=sum(r.pending for r in rows),
            cancelled=sum(r.cancelled for r in rows),
            amount=sum(r.amount for r in rows),
            paid=sum(r.paid for r in rows),
            # `r.due` уже полічений без скасованих (див. коментар у запиті
            # вище), тож проста сума по датах не тягне їх назад -- і тут
            # `amount - paid != due` так само навмисно.
            due=sum(r.due for r in rows),
        ))
    return groups, pagination
