"""Довідник локацій: підбір перекладу, фолбек, виявлення нових локацій
і наскрізний рендер у розкладі.

Назви локацій у тестах унікальні: conftest не прив'язує db.session до
відкатної транзакції, тож commit() лишається в тестовій БД між тестами.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask_babel import force_locale

from app.extensions import db
from app.models.city import City, normalize_city_name
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.services import city_glossary


def _uniq(prefix):
    return f'{prefix}-{uuid4().hex[:6]}'


def _city(name, ru=None, en=None):
    c = City(name=name)
    db.session.add(c)
    if ru:
        c.set_translation('ru', 'name', ru)
    if en:
        c.set_translation('en', 'name', en)
    db.session.commit()
    return c


def _instance(location, slug=None):
    course = Course(title='Курс', slug=slug or _uniq('c'), is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, location=location, event_format='offline',
        status='published',
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(inst)
    db.session.commit()
    return course, inst


def _clear_cache():
    """Глосарій кешується на g -- між перевірками кеш треба скидати."""
    from flask import g
    g.pop(city_glossary._CACHE_ATTR, None)


# --- нормалізація -----------------------------------------------------------

def test_normalize_collapses_case_and_spaces():
    assert normalize_city_name('  Харків  ') == 'харків'
    assert normalize_city_name('Кривий  Ріг') == 'кривий ріг'


def test_name_normalized_is_kept_in_sync():
    c = City(name='  Львів ')
    assert c.name_normalized == 'львів'
    c.name = 'Одеса'
    assert c.name_normalized == 'одеса'


# --- підбір перекладу -------------------------------------------------------

def test_localize_returns_translation(app):
    uk, ru, en = _uniq('Харків'), _uniq('Харьков'), _uniq('Kharkiv')
    _city(uk, ru=ru, en=en)
    _clear_cache()
    with force_locale('ru'):
        assert city_glossary.localize_location(uk) == ru
    with force_locale('en'):
        assert city_glossary.localize_location(uk) == en


def test_localize_matches_regardless_of_case_and_spacing(app):
    uk, ru = _uniq('Кривий Ріг'), _uniq('Кривой Рог')
    _city(uk, ru=ru)
    _clear_cache()
    with force_locale('ru'):
        assert city_glossary.localize_location(f'  {uk.upper()}  ') == ru


def test_localize_falls_back_to_source(app):
    uk = _uniq('Київ')
    _city(uk, ru=_uniq('Киев'))
    _clear_cache()
    with force_locale('ru'):
        # Немає в довіднику -> оригінал, а не порожньо.
        absent = _uniq('Полтава')
        assert city_glossary.localize_location(absent) == absent
    with force_locale('en'):
        # Є в довіднику, але без en-перекладу -> українська.
        assert city_glossary.localize_location(uk) == uk


def test_localize_passes_through_empty(app):
    _clear_cache()
    assert city_glossary.localize_location('') == ''
    assert city_glossary.localize_location(None) is None


def test_broken_glossary_does_not_break_pages(app, monkeypatch, caplog):
    """Довідник -- декоративний шар. Якщо таблиці ще немає (код піднявся до
    міграції) або БД моргнула, показуємо оригінал, а не 500 на кожній
    публічній сторінці."""
    import app.models.city as city_module

    class Boom:
        @property
        def query(self):
            raise RuntimeError('no such table: cities')

    monkeypatch.setattr(city_module, 'City', Boom())
    _clear_cache()
    assert city_glossary.localize_location('Харків') == 'Харків'
    assert 'City glossary unavailable' in caplog.text


def test_location_usage_counts_instances_per_location(app):
    location = _uniq('Житомир')
    _instance(location)
    _instance(location)
    _clear_cache()
    entry = city_glossary.location_usage()[normalize_city_name(location)]
    assert entry == {'name': location, 'count': 2}


def test_location_usage_merges_different_spellings(app):
    """Звірка йде за нормалізованою формою, тож "  МІСТО " і "Місто" -- одна
    локація, а не дві з лічильником 1."""
    location = _uniq('Ужгород')
    _instance(f'  {location.upper()}  ')
    _instance(location)
    _clear_cache()
    usage = city_glossary.location_usage()
    assert usage[normalize_city_name(location)]['count'] == 2


def test_unknown_locations_lists_only_missing(app):
    known, unknown = _uniq('Харків'), _uniq('Полтава')
    _instance(known)
    _instance(unknown)
    _city(known, ru=_uniq('Харьков'))
    _clear_cache()
    missing = city_glossary.unknown_locations()
    assert unknown in missing
    assert known not in missing


# --- наскрізь у розкладі ----------------------------------------------------

def test_schedule_badge_shows_translated_city(get_localized):
    slug, uk, ru = _uniq('loc'), _uniq('Харків'), _uniq('Харьков')
    _instance(uk, slug=slug)
    _city(uk, ru=ru)
    _clear_cache()

    page_ru = get_localized(f'/ru/courses/{slug}').get_data(as_text=True)
    assert ru in page_ru

    _clear_cache()
    page_uk = get_localized(f'/courses/{slug}').get_data(as_text=True)
    assert uk in page_uk
    assert ru not in page_uk


def test_jsonld_keeps_canonical_ukrainian(get_localized):
    """JSON-LD, ICS і партнерське API лишаються на канонічних укр-даних:
    локалізуємо лише те, що читає людина."""
    slug, uk, ru = _uniq('loc'), _uniq('Харків'), _uniq('Харьков')
    _instance(uk, slug=slug)
    _city(uk, ru=ru)
    _clear_cache()

    page = get_localized(f'/ru/courses/{slug}').get_data(as_text=True)
    start = page.find('application/ld+json')
    jsonld = page[start:page.find('</script>', start)]
    assert '"@type": "Place"' in jsonld
    assert ru not in jsonld
