"""Фільтр «заходи цього тренера» з тим самим fallback, що й у моделі."""
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.services import trainer_links


def _trainer():
    t = Trainer(full_name=f'Т {uuid4().hex[:4]}', slug=uuid4().hex[:8])
    db.session.add(t)
    db.session.commit()
    return t


def _instance(course_trainers_ids=(), own_ids=()):
    course = Course(title=f'К {uuid4().hex[:4]}', slug=uuid4().hex[:8])
    db.session.add(course)
    db.session.commit()
    trainer_links.set_trainers(course, list(course_trainers_ids))
    instance = CourseInstance(course_id=course.id)
    db.session.add(instance)
    db.session.commit()
    trainer_links.set_trainers(instance, list(own_ids))
    db.session.commit()
    return instance


def _matches(trainer_id):
    return {
        row.id for row in CourseInstance.query.filter(
            trainer_links.instance_trainer_clause(trainer_id)
        ).all()
    }


def test_matches_when_trainer_is_on_the_instance():
    t = _trainer()
    inst = _instance(own_ids=[t.id])
    assert inst.id in _matches(t.id)


def test_matches_when_inherited_from_course():
    t = _trainer()
    inst = _instance(course_trainers_ids=[t.id])
    assert inst.id in _matches(t.id)


def test_instance_list_hides_course_trainer():
    """Проведення вказало своїх -- курсові більше не рахуються."""
    course_only, own = _trainer(), _trainer()
    inst = _instance(course_trainers_ids=[course_only.id], own_ids=[own.id])
    assert inst.id in _matches(own.id)
    assert inst.id not in _matches(course_only.id)


def test_no_match_when_trainer_is_elsewhere():
    t, other = _trainer(), _trainer()
    inst = _instance(course_trainers_ids=[other.id])
    assert inst.id not in _matches(t.id)
