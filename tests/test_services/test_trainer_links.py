"""Запис переліку тренерів заходу зі збереженням порядку."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.trainer import Trainer
from app.models.trainer_links import course_trainers
from app.services import trainer_links


def _trainer(name):
    t = Trainer(full_name=name, slug=uuid4().hex[:8])
    db.session.add(t)
    db.session.commit()
    return t


def _course():
    c = Course(title=f'Курс {uuid4().hex[:4]}', slug=uuid4().hex[:8])
    db.session.add(c)
    db.session.commit()
    return c


def _positions(course):
    rows = db.session.execute(
        course_trainers.select()
        .where(course_trainers.c.course_id == course.id)
        .order_by(course_trainers.c.position)
    ).all()
    return [(r.trainer_id, r.position) for r in rows]


def test_numbers_positions_from_zero():
    course, a, b = _course(), _trainer('А'), _trainer('Б')
    trainer_links.set_trainers(course, [a.id, b.id])
    db.session.commit()
    assert _positions(course) == [(a.id, 0), (b.id, 1)]


def test_drops_duplicates_keeping_first_occurrence():
    course, a, b = _course(), _trainer('А'), _trainer('Б')
    trainer_links.set_trainers(course, [a.id, b.id, a.id])
    db.session.commit()
    assert _positions(course) == [(a.id, 0), (b.id, 1)]


def test_rewrites_the_whole_list():
    course, a, b, c = _course(), _trainer('А'), _trainer('Б'), _trainer('В')
    trainer_links.set_trainers(course, [a.id, b.id])
    db.session.commit()
    trainer_links.set_trainers(course, [c.id])
    db.session.commit()
    assert _positions(course) == [(c.id, 0)]


def test_empty_list_clears():
    course, a = _course(), _trainer('А')
    trainer_links.set_trainers(course, [a.id])
    db.session.commit()
    trainer_links.set_trainers(course, [])
    db.session.commit()
    assert _positions(course) == []


def test_rejects_unknown_entity_type():
    with pytest.raises(TypeError):
        trainer_links.set_trainers(object(), [])


def test_does_not_discard_unflushed_scalar_changes():
    """set_trainers не має чіпати НЕПОВʼЯЗАНІ атрибути сутності.

    Раніше set_trainers завершувався бланкетним db.session.expire(entity)
    (без списку атрибутів) -- expire ВСІХ атрибутів. Викликач, що щойно
    (як у адмінських роутах) дістав сутність через db.session.get і виставив
    на ній звичайний (не relationship) атрибут -- ще не зафлашивши -- тихо,
    без жодної помилки, отримував відкат цієї зміни до останнього
    зафлашеного значення. Саме так форма курсу/проведення губила щойно
    введені дані (title, slug, ціни тощо), щойно з'являвся виклик
    set_trainers після populate_*_from_form.

    expire_all() + повторний db.session.get -- щоб course був у тому самому
    стані, в якому set_trainers застає сутність у реальному роуті (свіжо
    завантажена з БД, НЕ той самий Python-обʼєкт, що тримав курс одразу
    після створення в цьому тесті): саме на цій формі стану бланкетний
    expire і губив зміни. Регресія ловить повернення до expire(entity) без
    списку атрибутів: title знову відкотився б на 'Original'.
    """
    course = _course()
    trainer = _trainer('А')
    course_id, trainer_id = course.id, trainer.id
    db.session.expire_all()

    fresh = db.session.get(Course, course_id)
    fresh.title = 'Changed but not flushed'
    trainer_links.set_trainers(fresh, [trainer_id])

    # Перелік тренерів мав застосуватись...
    assert [t.id for t in fresh.trainers] == [trainer_id]
    # ...а незвʼязаний скалярний атрибут -- лишитись як виставив викликач,
    # ще ДО commit (тобто expire не встиг його "забути").
    assert fresh.title == 'Changed but not flushed'

    db.session.commit()
    assert db.session.get(Course, course_id).title == 'Changed but not flushed'


def test_position_assigned_by_input_order_not_sorted_ids():
    """Position нумерується в порядку переданого списку, а не за id.

    Порядок передачі тут НАВМИСНЕ спадний за id: спершу створюємо A
    (менший id), потім B (більший), а передаємо [B, A]. Реалізація, що
    нумерує position за sorted(trainer_id), дала б [(A, 0), (B, 1)] і на
    цьому тесті впала б -- саме тому порядок і має розходитись зі
    зростанням id. Без цього розходження тест мовчки пропустив би
    помилку, яка ламає правило «перший тренер = головний лектор».
    """
    course = _course()
    a = _trainer('А')          # створений першим -> менший id
    b = _trainer('Б')          # створений другим -> більший id
    assert a.id < b.id, 'передумова тесту: id зростають за порядком insert'

    trainer_links.set_trainers(course, [b.id, a.id])   # спадний за id
    db.session.commit()

    assert _positions(course) == [(b.id, 0), (a.id, 1)]
