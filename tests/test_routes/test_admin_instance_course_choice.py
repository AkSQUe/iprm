"""Курс у формі ПРОВЕДЕННЯ не підміняється, коли сам курс вимкнений.

Список «Курс» будується з активних курсів. Якщо курс проведення вимкнений,
у <select> немає варіанта з поточним значенням, браузер підставляє перший
за алфавітом, і збереження форми з будь-якої іншої причини мовчки переносить
дату на чужий курс. 26.10.2026 так дата 24.10 переїхала з «Плазмотерапії в
травматології...» на «BioSmart Dentistry», і група, що ще не склала тест,
втратила його: тест береться з курсу проведення.
"""
import re
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.user import User


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'icc-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    # Прибираємо за собою: інакше валиться test_api_v1_clients.
    db.session.delete(user)
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _course(title, is_active=True):
    course = Course(title=title, slug=uuid4().hex[:8], is_active=is_active)
    db.session.add(course)
    db.session.commit()
    return course


def _course_options(html):
    """(value, selected) кожного <option> у select#course_id."""
    match = re.search(
        r'<select[^>]*id="course_id"[^>]*>(.*?)</select>', html, re.DOTALL,
    )
    assert match, 'у формі немає select#course_id'
    options = []
    for tag in re.findall(r'<option[^>]*>', match.group(1)):
        value = re.search(r'value="(\d+)"', tag)
        options.append((int(value.group(1)), 'selected' in tag))
    return options


def test_inactive_course_of_instance_stays_selected_and_survives_save(client, admin):
    _login(client, admin)
    tag = uuid4().hex[:4]
    # Активний курс, що за алфавітом стоїть першим, -- саме його браузер
    # підставив би замість відсутнього варіанта.
    decoy = _course(f'AAA приманка {tag}')
    own = _course(f'Плазмотерапія {tag}', is_active=False)
    instance = CourseInstance(course_id=own.id, status='draft', event_format='offline')
    db.session.add(instance)
    db.session.commit()

    html = client.get(f'/admin/instances/{instance.id}/edit').get_data(as_text=True)
    options = _course_options(html)
    assert (own.id, True) in options
    assert (decoy.id, False) in options

    selected = [value for value, is_selected in options if is_selected]
    response = client.post(f'/admin/instances/{instance.id}/edit', data={
        'course_id': str(selected[0]),
        'start_date': '2026-01-15T10:00',
        'event_format': 'offline',
        'status': 'draft',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert db.session.get(CourseInstance, instance.id).course_id == own.id


def test_other_inactive_courses_stay_out_of_the_list(client, admin):
    _login(client, admin)
    tag = uuid4().hex[:4]
    active = _course(f'Активний {tag}')
    hidden = _course(f'Вимкнений чужий {tag}', is_active=False)
    instance = CourseInstance(course_id=active.id, status='draft', event_format='offline')
    db.session.add(instance)
    db.session.commit()

    html = client.get(f'/admin/instances/{instance.id}/edit').get_data(as_text=True)
    values = [value for value, _ in _course_options(html)]
    assert active.id in values
    assert hidden.id not in values
