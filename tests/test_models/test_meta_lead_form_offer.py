"""Прив'язка Meta-форми до заходу ІПРМ.

Прив'язка саме до ФОРМИ, а не до кампанії: людина заповнювала форму, і одна
кампанія цілком веде дві форми на різні заходи.

Найдорожча межа тут -- видалення заходу. Знести разом із ним схему форми
означало б втратити підписи питань для ВСІХ уже наявних заявок, і картка
ліда знову показувала б внутрішні ключі Meta.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.meta_lead import MetaLeadForm


def _instance():
    course = Course(title='Плазмотерапія: базовий курс', slug=f'pl-{id(object())}')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id,
        start_date=datetime.now(timezone.utc) + timedelta(days=14),
        status='published',
    )
    db.session.add(instance)
    db.session.flush()
    return instance


def test_form_can_point_at_an_event(app):
    instance = _instance()
    form = MetaLeadForm(form_id='900', questions={},
                        course_instance_id=instance.id)
    db.session.add(form)
    db.session.commit()

    assert form.course_instance.id == instance.id


def test_form_without_an_event_is_valid(app):
    """Форма може бути не про конкретний захід -- прив'язка необов'язкова."""
    form = MetaLeadForm(form_id='901', questions={})
    db.session.add(form)
    db.session.commit()

    assert form.course_instance_id is None


def test_deleting_the_event_keeps_the_schema(app):
    """Схема переживає видалення заходу: без неї підписи питань зникли б."""
    instance = _instance()
    form = MetaLeadForm(form_id='902', questions={'q': {'label': 'Питання'}},
                        course_instance_id=instance.id)
    db.session.add(form)
    db.session.commit()

    db.session.delete(instance)
    db.session.commit()

    fresh = MetaLeadForm.query.filter_by(form_id='902').one()
    assert fresh.course_instance_id is None
    assert fresh.questions == {'q': {'label': 'Питання'}}
