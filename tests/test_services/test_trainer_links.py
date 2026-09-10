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


def test_position_assigned_by_input_order_not_sorted_ids():
    """Position нумерується в порядку переданого списку, не за id.

    На позиціях зберігається порядок введення: якщо лектор В передав
    ДО лектора А (хоч A.id < B.id), перший тренер -- В, другий -- А.
    Реалізація, що нумерує position за sorted(trainer_id), стерпить
    цей тест, але порушить логіку «перший тренер = lead lecturer».
    """
    course = _course()
    b = _trainer('Б')  # Створена друга
    a = _trainer('А')  # Створена перша, тому A.id > B.id (порядок insert)
    # Передаємо в зворотному порядку: B перший, A другий
    trainer_links.set_trainers(course, [b.id, a.id])
    db.session.commit()
    # Позиції мають відповідати порядку передачі, не сортування по id
    assert _positions(course) == [(b.id, 0), (a.id, 1)]
