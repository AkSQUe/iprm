"""Запис і запити по звʼязку «захід -- тренери».

Одна функція запису на обидві таблиці: три переклади того самого
правила розійшлись би, і розбіжність було б видно лише як «у фільтрі
захід є, у списку немає».
"""
from app.extensions import db
from app.models.trainer_links import course_instance_trainers, course_trainers


def _table_and_key(entity):
    from app.models.course import Course
    from app.models.course_instance import CourseInstance
    if isinstance(entity, Course):
        return course_trainers, 'course_id'
    if isinstance(entity, CourseInstance):
        return course_instance_trainers, 'instance_id'
    raise TypeError(
        f'Немає таблиці звʼязку тренерів для {type(entity).__name__}'
    )


def set_trainers(entity, trainer_ids):
    """Перезаписати перелік тренерів сутності, зберігши порядок.

    Дублікати відсіюються зі збереженням ПЕРШОГО входження; position
    нумерується з нуля без пропусків. Commit -- на викликачі.
    """
    table, key = _table_and_key(entity)
    if entity.id is None:
        # Нова сутність ще не має id: без flush INSERT пішов би з NULL.
        db.session.flush()

    ordered, seen = [], set()
    for raw in trainer_ids or []:
        tid = int(raw)
        if tid and tid not in seen:
            seen.add(tid)
            ordered.append(tid)

    db.session.execute(table.delete().where(table.c[key] == entity.id))
    if ordered:
        db.session.execute(table.insert(), [
            {key: entity.id, 'trainer_id': tid, 'position': pos}
            for pos, tid in enumerate(ordered)
        ])
    # Relationship уже міг завантажитись у цій сесії -- без expire читач
    # побачив би старий список.
    db.session.expire(entity)
