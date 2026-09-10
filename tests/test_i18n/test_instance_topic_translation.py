"""Тема проведення в каналі перекладів: реєстр сутностей і xlsx-аркуші.

Без цього тему заводили б українською, а ru/en-сторінка розкладу називала б
захід назвою курсу -- тобто одна й та сама дата звалась би по-різному
залежно від мови.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.services import translation_registry as registry
from app.services import xlsx_translations


def _instance(topic='PRP у практиці ортопеда'):
    course = Course(title='Базовий курс', slug=f'itr-{uuid4().hex[:6]}',
                    is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, topic=topic, status='published',
        start_date=datetime.now(timezone.utc) + timedelta(days=10),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def test_instance_is_a_translatable_entity():
    entry = registry.entity_registry()['course_instance']
    assert entry['model'] is CourseInstance
    assert entry['label'] == 'Проведення'


def test_topic_is_a_translation_unit():
    inst = _instance()
    units = {u.uid: u for u in registry.units(inst)}
    assert units['topic'].source == 'PRP у практиці ортопеда'
    assert units['topic'].label == 'Тема'


def test_applied_translation_reaches_the_page():
    inst = _instance()
    registry.apply_units(inst, 'ru', {'topic': 'PRP в практике ортопеда'})
    assert inst.effective_title_for('ru') == 'PRP в практике ортопеда'


def test_instance_without_topic_stays_out_of_the_translator_file():
    """Проведення, що бере назву курсу, перекладати нічим -- у файлі його
    рядка бути не повинно."""
    inst = _instance(topic=None)
    db.session.flush()
    sheets = list(xlsx_translations.SCOPES['instances'][1]())
    rows = next(rows for title, _e, rows in sheets if title == 'Проведення')
    assert all(obj.id != inst.id for obj, _label in rows)


def test_xlsx_schedule_scope_offers_instances():
    inst = _instance()
    db.session.flush()
    sheets = list(xlsx_translations.SCOPES['instances'][1]())
    titles = {sheet_title for sheet_title, _entity, _rows in sheets}
    assert 'Проведення' in titles
    rows = next(rows for title, _e, rows in sheets if title == 'Проведення')
    assert any(obj.id == inst.id for obj, _label in rows)
