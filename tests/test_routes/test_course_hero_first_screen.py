"""Перший екран сторінки заходу: що на ньому стоїть і в якому порядку.

Редизайн 10.09.2026. Три рішення, які легко зламати непомітно:

* дата й адреса живуть у КАРТЦІ проведення, а не чипом над заголовком --
  чип із повною адресою розтягувався на два рядки й читався як плашка;
* рядки картки йдуть у порядку питань відвідувача: коли -> чи ще беруть ->
  скільки лишилось -> яке місто -> яка адреса. Порядок -- продуктове
  рішення, а не побічний ефект верстки;
* кегль заголовка зменшується модифікатором за ДОВЖИНОЮ назви: клемп у CSS
  знає лише ширину екрана, і назва в 96 символів давала п'ять рядків.
"""
import re

from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.city import City
from app.models.course import Course
from app.models.course_instance import CourseInstance

LONG_TITLE = ('Біль у суглобах і відновлення після травм: сучасні '
              'PRP-протоколи для ортопеда-травматолога')
ADDRESS = 'вул. Григорія Сковороди, 80, ДУ «ІПХС ім. проф. М. І. Ситенка»'


@pytest.fixture(autouse=True)
def clean():
    """Прибирати за собою обов'язково: курси цього файлу інакше рахуються
    в переліках, мапі сайту й лічильниках інших тестів повного прогону."""
    def _wipe():
        Course.query.filter(Course.slug.like('first-screen%')).delete(
            synchronize_session=False)
        City.query.filter(City.name == 'Харків').delete(
            synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


def _course(slug, *, title='Курс першого екрана', tags=None, with_city=True):
    course = Course(slug=slug, title=title, is_active=True,
                    event_type='course', tags=tags or [], max_participants=10)
    db.session.add(course)
    db.session.flush()

    city = None
    if with_city:
        city = City.query.filter_by(name='Харків').first() or City(name='Харків')
        db.session.add(city)
        db.session.flush()

    db.session.add(CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        location=ADDRESS, city_id=city.id if city else None,
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
        max_participants=10,
    ))
    db.session.commit()
    return course


def _hero(html):
    """Розмітка hero: від секції до рядка ключових параметрів включно."""
    start = html.index('iprm-hero--landing')
    return html[start:html.index('</section>', start)]


def test_card_rows_follow_the_visitors_questions(client):
    course = _course('first-screen-order')
    card = _hero(client.get(f'/courses/{course.slug}').get_data(as_text=True))
    card = card[card.index('iprm-hero__seats"'):]

    order = [card.index(cls) for cls in (
        'iprm-hero__seats-date',
        'iprm-hero__seats-kicker',
        'iprm-hero__seats-value',
        'iprm-progress',
        'iprm-hero__seats-city',
        'iprm-hero__seats-note',
    )]
    assert order == sorted(order), 'порядок рядків картки проведення змінився'


def test_city_and_address_are_separate_rows(client):
    course = _course('first-screen-city')
    hero = _hero(client.get(f'/courses/{course.slug}').get_data(as_text=True))
    city_row = re.search(r'iprm-hero__seats-city">([^<]*)<', hero).group(1)
    note_row = re.search(r'iprm-hero__seats-note">([^<]*)<', hero).group(1)
    assert city_row.strip() == 'Харків'
    assert 'Сковороди' in note_row


def test_date_is_in_the_card_and_not_a_chip(client):
    course = _course('first-screen-date')
    hero = _hero(client.get(f'/courses/{course.slug}').get_data(as_text=True))
    chips = hero[hero.index('iprm-hero__chips'):hero.index('iprm-hero__title')]
    assert 'Сковороди' not in chips, 'адреса повернулась у чипи'
    assert '<time datetime=' in hero, 'дата має бути машинозчитуваною'


def test_editor_tag_does_not_repeat_the_event_type(client):
    """Редактори вписують "Курс" тегом, не знаючи, що вид заходу вже дав чип."""
    course = _course('first-screen-dup', tags=['курс', 'Базовий'])
    hero = _hero(client.get(f'/courses/{course.slug}').get_data(as_text=True))
    chips = re.findall(r'iprm-hero__chip[^"]*">([^<]*)<', hero)
    lowered = [c.strip().lower() for c in chips]
    assert len(lowered) == len(set(lowered)), f'дубль серед чипів: {chips}'
    assert 'базовий' in lowered


def test_long_title_gets_a_smaller_step(client):
    short = _course('first-screen-short', title='PRP у травматології')
    html = client.get(f'/courses/{short.slug}').get_data(as_text=True)
    assert 'iprm-hero__title--' not in html

    long_one = _course('first-screen-long', title=LONG_TITLE)
    html = client.get(f'/courses/{long_one.slug}').get_data(as_text=True)
    assert 'iprm-hero__title--xlong' in html
