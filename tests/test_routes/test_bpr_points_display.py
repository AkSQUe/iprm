"""Показ балів БПР на публічних сторінках.

Гібридний захід дає різні бали за формат участі (онлайн/очно), тому
сторінка курсу й тег розкладу мусять показувати ОБИДВА значення, а не
одне число, як робив старий effective_cpd_points. Перевіряємо не сам факт
появи цифр (вони трапляються на сторінці завжди), а що вони підписані
форматом і що сирий Decimal ('7.50') на сторінку не просочується.
"""
from decimal import Decimal

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
    course, _ = _published_hybrid(app)
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    online_pos = html.find('7,5')
    offline_pos = html.find('9')
    assert online_pos != -1 and offline_pos != -1
    # "Онлайн" і "Офлайн" мусять стояти поруч зі "своїми" цифрами -- інакше
    # це просто два числа, що трапились на сторінці з інших причин.
    assert 'Онлайн 7,5' in html
    assert 'Офлайн 9' in html
    assert '7.50' not in html
    assert '9.00' not in html


def test_schedule_tag_shows_range(client, app):
    _published_hybrid(app)
    html = client.get('/courses/').get_data(as_text=True)
    # Діапазон у тегу картки/розкладу -- обидва значення в межах одного
    # тега, з en-dash між ними (points_range), а не окремо десь на сторінці.
    assert '7,5&ndash;9' in html or '7,5–9' in html
    assert '7.50' not in html
    assert '9.00' not in html
