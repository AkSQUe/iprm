"""Запис і запити по звʼязку «захід -- тренери».

Одна функція запису на обидві таблиці: три переклади того самого
правила розійшлись би, і розбіжність було б видно лише як «у фільтрі
захід є, у списку немає».
"""
from sqlalchemy import and_, exists, not_, or_, select

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
    # Звужено до 'trainers': relationship viewonly=True, тож сам ніколи не
    # тримає pending-змін -- expire саме його примушує до перезавантаження,
    # якого вимагає щойно виконаний DELETE/INSERT по таблиці звʼязку.
    # Бланкетний db.session.expire(entity) (без списку атрибутів) експайрить
    # УСІ атрибути сутності, включно з тими, що викликач міг виставити перед
    # цим викликом і ще не встиг зафлашити, -- і тихо викидає їх, без жодної
    # помилки. Це саме той баг, що зʼїв trainer_ids-форму курсу/проведення.
    db.session.expire(entity, ['trainers'])


def course_trainer_clause(trainer_id):
    """Курс веде цей тренер. Без fallback -- курсу успадковувати нема від кого."""
    from app.models.course import Course
    return exists(select(1).where(and_(
        course_trainers.c.course_id == Course.id,
        course_trainers.c.trainer_id == trainer_id,
    )))


def instance_trainer_clause(trainer_id):
    """Проведення веде цей тренер -- із тим самим fallback, що й у моделі.

    Перелік проведення перекриває курсовий ПОВНІСТЮ, тож курс
    перевіряється лише тоді, коли у проведення немає ЖОДНОГО свого
    тренера. Одна функція на всіх споживачів: три переклади цього
    правила розійшлись би, і розбіжність було б видно лише як
    «у фільтрі захід є, у списку немає».
    """
    from app.models.course_instance import CourseInstance

    own = exists(select(1).where(and_(
        course_instance_trainers.c.instance_id == CourseInstance.id,
        course_instance_trainers.c.trainer_id == trainer_id,
    )))
    has_any_own = exists(select(1).where(
        course_instance_trainers.c.instance_id == CourseInstance.id
    ))
    inherited = exists(select(1).where(and_(
        course_trainers.c.course_id == CourseInstance.course_id,
        course_trainers.c.trainer_id == trainer_id,
    )))
    return or_(own, and_(not_(has_any_own), inherited))
