"""Служба довідника видів заходів: назви, відмінки, choices, usage."""
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.event_type import EventType
from app.services import event_types


def _custom(code=None, **kw):
    """Власний рядок довідника. Прибираємо за собою: таблиця глобальна."""
    row = EventType(code=code or f'z-{uuid4().hex[:6]}',
                    name=kw.pop('name', 'Тестовий тип'),
                    sort_order=kw.pop('sort_order', 500), **kw)
    db.session.add(row)
    db.session.flush()
    event_types.reset_cache()
    return row


def test_label_returns_seeded_name(app):
    assert event_types.label('seminar') == 'Семінар'


def test_label_of_unknown_code_returns_the_code(app):
    assert event_types.label('no-such-type') == 'no-such-type'


def test_label_of_empty_code_is_empty(app):
    assert event_types.label(None) is None
    assert event_types.label('') == ''


def test_label_uses_translation_when_present(app, db_session):
    row = _custom(name='Тренінг')
    row.set_translation('en', 'name', 'Training')
    event_types.reset_cache()

    assert event_types.label(row.code, lang='en') == 'Training'
    assert event_types.label(row.code, lang='ru') == 'Тренінг'


def test_accusative_and_genitive_come_from_directory(app):
    assert event_types.accusative('scientific_conference') == 'наукову конференцію'
    assert event_types.genitive('scientific_conference') == 'наукової конференції'


def test_cases_fall_back_to_lowered_name(app, db_session):
    row = _custom(name='Вебмарафон')
    assert event_types.accusative(row.code) == 'вебмарафон'
    assert event_types.genitive(row.code) == 'вебмарафон'


def test_cases_of_unknown_code_fall_back_to_the_code(app):
    assert event_types.accusative('mystery') == 'mystery'
    assert event_types.genitive(None) is None


def test_choices_hold_active_types_in_seed_order(app):
    codes = [code for code, _ in event_types.choices()]
    assert codes[:3] == ['seminar', 'scientific_conference', 'elearning_course']
    assert 'course' not in codes, 'застарілий тип не пропонується у виборі'


def test_choices_add_current_even_when_deactivated(app):
    codes = dict(event_types.choices(current='course'))
    assert 'course' in codes
    assert 'застарілий' in codes['course']


def test_choices_do_not_duplicate_current_when_active(app):
    codes = [code for code, _ in event_types.choices(current='seminar')]
    assert codes.count('seminar') == 1
