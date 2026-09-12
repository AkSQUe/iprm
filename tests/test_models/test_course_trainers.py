"""Перелік тренерів заходу: порядок, успадкування, головний."""
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
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


def _instance(course):
    i = CourseInstance(course_id=course.id)
    db.session.add(i)
    db.session.commit()
    return i


def test_trainers_follow_position_not_insertion_id():
    course, a, b = _course(), _trainer('Яременко'), _trainer('Андрієнко')
    trainer_links.set_trainers(course, [b.id, a.id])
    db.session.commit()
    assert [t.id for t in course.trainers] == [b.id, a.id]


def test_course_trainer_is_the_first_one():
    course, a, b = _course(), _trainer('А'), _trainer('Б')
    trainer_links.set_trainers(course, [b.id, a.id])
    db.session.commit()
    assert course.trainer.id == b.id


def test_course_without_trainers_has_none():
    assert _course().trainer is None


def test_instance_inherits_course_list_when_empty():
    course, a, b = _course(), _trainer('А'), _trainer('Б')
    trainer_links.set_trainers(course, [a.id, b.id])
    db.session.commit()
    instance = _instance(course)
    assert [t.id for t in instance.effective_trainers] == [a.id, b.id]


def test_instance_list_overrides_course_list_entirely():
    course, a, b, c = _course(), _trainer('А'), _trainer('Б'), _trainer('В')
    trainer_links.set_trainers(course, [a.id, b.id])
    db.session.commit()
    instance = _instance(course)
    trainer_links.set_trainers(instance, [c.id])
    db.session.commit()
    # Часткового злиття немає: проведення вказало тренерів -- отже, всіх.
    assert [t.id for t in instance.effective_trainers] == [c.id]


def test_effective_trainer_is_first_of_effective_list():
    course, a, b = _course(), _trainer('А'), _trainer('Б')
    trainer_links.set_trainers(course, [a.id, b.id])
    db.session.commit()
    assert _instance(course).effective_trainer.id == a.id


def test_online_course_exposes_single_trainer_as_list():
    from uuid import uuid4 as _uuid4
    from app.models.online_course import OnlineCourse
    a = _trainer('А')
    oc = OnlineCourse(
        sintegrum_id=_uuid4().int % 10**8,
        remote_name='Онлайн',
        slug=uuid4().hex[:8],
        trainer_id=a.id,
    )
    db.session.add(oc)
    db.session.commit()
    assert [t.id for t in oc.trainers] == [a.id]
    oc.trainer_id = None
    db.session.commit()
    assert oc.trainers == []
