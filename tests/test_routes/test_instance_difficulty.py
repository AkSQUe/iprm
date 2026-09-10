"""Рівень складності проведення в адмінці: поле, підпис порожнього вибору, збереження."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def instance(app):
    course = Course(title='Базовий курс', slug=f'dif-{_uid()}',
                    short_description='d', is_active=True, base_price=100,
                    difficulty_level=2)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _form(app, instance):
    from app.admin.forms import CourseInstanceForm
    from app.admin.routes_instances import _populate_choices

    with app.test_request_context():
        form = CourseInstanceForm(obj=instance)
        _populate_choices(form, instance=instance)
    return form


def _save(app, instance, level):
    """Провести обраний у пікері рівень тим самим шляхом, що й адмінка."""
    from app.services import course_service

    with app.test_request_context():
        form = _form(app, instance)
        form.difficulty_level.data = level
        course_service.populate_instance_from_form(instance, form)
    return instance


class TestForm:
    def test_level_is_optional_and_offers_the_whole_scale(self, app, instance):
        form = _form(app, instance)
        values = [value for value, _label in form.difficulty_level.choices]
        assert values == [0, 1, 2, 3]
        assert not form.difficulty_level.flags.required

    def test_empty_choice_names_the_inherited_level(self, app, instance):
        """Голе «Як у курсу» не повідомляє нічого: щоб дізнатись рівень,
        довелось би відкрити картку курсу. Той самий підпис, що у виду заходу."""
        form = _form(app, instance)
        assert form.difficulty_level.choices[0][1] == (
            '– Як у курсу (Рівень 2 — просунутий) –')

    def test_empty_choice_stays_bare_when_the_course_has_no_level(self, app, instance):
        instance.course.difficulty_level = None
        db.session.flush()
        form = _form(app, instance)
        assert form.difficulty_level.choices[0][1] == '– Як у курсу –'


class TestSaving:
    def test_chosen_level_overrides_the_course(self, app, instance):
        _save(app, instance, 3)
        assert instance.difficulty_level == 3
        assert instance.effective_difficulty_level == 3

    def test_empty_choice_becomes_null_not_zero(self, app, instance):
        """Нуль із пікера -- це «як у курсу», і в БД він мусить лягти NULL:
        `effective_difficulty_level` перевіряє істинність, а колонка з нулями
        робила б його правильним лише випадково."""
        instance.difficulty_level = 3
        db.session.flush()

        _save(app, instance, 0)

        assert instance.difficulty_level is None
        assert instance.effective_difficulty_level == 2
