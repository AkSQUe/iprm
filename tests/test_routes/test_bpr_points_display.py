"""Показ балів БПР на публічних сторінках.

Гібридний захід дає різні бали за формат участі (онлайн/очно), тому
сторінка курсу й тег розкладу мусять показувати ОБИДВА значення, а не
одне число, як робив старий effective_cpd_points. Перевіряємо не сам факт
появи цифр (вони трапляються на сторінці завжди), а що вони підписані
форматом і що сирий Decimal ('7.50') на сторінку не просочується.
"""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal

from app.courses.routes import _serialize_event
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance


def _published_hybrid(app):
    course = Course(title='Гібрид', slug='hybrid-bpr', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, event_format='hybrid', status='published',
        cpd_points_online=Decimal('7.50'), cpd_points_offline=Decimal('9.00'),
    )
    db.session.add(inst)
    db.session.commit()
    return course, inst


def test_course_page_shows_both_formats(client, app):
    """Різні бали за формат -- ДВІ клітинки рядка параметрів hero.

    Перевіряємо саме пару "число + його підпис У ТІЙ САМІЙ клітинці": два
    числа й два слова, розкидані по сторінці, нічого не доводять. Раніше
    бали стояли окремим чипом під hero одним рядком ("Онлайн 7,5 · Офлайн
    9"), тепер -- клітинками, бо в рядку 20px/700 той рядок ламався
    посередині.
    """
    course, _ = _published_hybrid(app)
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    cells = re.findall(
        r'<div class="iprm-hero__meta-item">(.*?)</div>', html, re.DOTALL,
    )
    online = [c for c in cells if 'Онлайн' in c]
    offline = [c for c in cells if 'Офлайн' in c]
    assert len(online) == 1 and len(offline) == 1, (
        'бали за формат мусять бути двома клітинками рядка параметрів'
    )
    assert '7,5' in online[0] and '9' not in online[0]
    assert '9' in offline[0] and '7,5' not in offline[0]
    assert '7.50' not in html
    assert '9.00' not in html


def test_course_page_shows_one_cell_when_formats_agree(client, app):
    """Однакові бали -- одна клітинка без підпису формату.

    Інакше сторінка двічі повідомляє те саме число й наводить на думку, що
    їх можна скласти.
    """
    course = Course(title='Однакові', slug='same-bpr', is_active=True)
    db.session.add(course)
    db.session.flush()
    db.session.add(CourseInstance(
        course_id=course.id, event_format='hybrid', status='published',
        cpd_points_online=Decimal('9.00'), cpd_points_offline=Decimal('9.00'),
    ))
    db.session.commit()

    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    cells = re.findall(
        r'<div class="iprm-hero__meta-item">(.*?)</div>', html, re.DOTALL,
    )
    assert not [c for c in cells if 'Онлайн' in c or 'Офлайн' in c]
    assert len([c for c in cells if 'балів БПР' in c]) == 1


def test_schedule_tag_shows_range(client, app):
    _published_hybrid(app)
    html = client.get('/courses/').get_data(as_text=True)
    # Діапазон у тегу картки/розкладу -- обидва значення в межах одного
    # тега, з en-dash між ними (points_range), а не окремо десь на сторінці.
    assert '7,5&ndash;9' in html or '7,5–9' in html
    assert '7.50' not in html
    assert '9.00' not in html


def test_serialized_event_uses_middle_dot_not_html_entity(app):
    # cpd_text їде в JSON і потім через escapeHtml у JS (page-courses-
    # schedule.js): якщо роздільник -- HTML-сутність &middot;, escapeHtml
    # перетворить & на &amp; і в календарі буде видно буквально "&middot;"
    # замість крапки. Символ має бути літеральним U+00B7.
    _course, inst = _published_hybrid(app)
    # _serialize_event форматує дату, тож для нього (на відміну від решти
    # тестів файлу) start_date має бути заповнена.
    inst.start_date = datetime(2027, 1, 10, tzinfo=timezone.utc)
    db.session.commit()
    payload = _serialize_event(inst, {})
    assert '·' in payload['cpd_text']
    assert '&middot;' not in payload['cpd_text']
    assert '&amp;' not in payload['cpd_text']


def test_course_schema_number_of_credits_uses_max_of_formats(client, app):
    # numberOfCredits у JSON-LD -- максимум із заповнених форматів, а не
    # "офлайн, якщо є" (or віддає перший непорожній операнд, а не більший).
    course = Course(
        title='Онлайн дорожчий', slug='online-more-bpr', is_active=True,
        cpd_points_online=Decimal('9.00'), cpd_points_offline=Decimal('7.50'),
    )
    db.session.add(course)
    db.session.commit()
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    # Сторінка має кілька <script type="application/ld+json">: організація
    # (base.html) і сам курс -- беремо саме @type "Course".
    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL,
    )
    schemas = [json.loads(b) for b in blocks]
    course_schema = next(s for s in schemas if s.get('@type') == 'Course')
    assert course_schema['numberOfCredits'] == 9.0
