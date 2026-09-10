"""Впорядковуваний мультиселект: у каталозі й на формі заходу.

Опційність за атрибутом -- ядро вимоги (задача 5): кнопки переставлення
мають зʼявлятись лише в парі з `data-multiselect-ordered`, а поле
спеціальностей (просто `data-multiselect`) лишається без них. Тому тут два
різні тести на форму курсу: один підтверджує присутність атрибута на полі
тренерів, другий -- що поле спеціальностей його НЕ отримало (без цього
регресія, що вмикає впорядкування всюди, пройшла б непоміченою).
"""
import re
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.user import User


def _uid():
    return uuid4().hex[:6]


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'ordms-{_uid()}@test.com', 'password123',
        first_name='O', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    # Прибираємо за собою: інакше валиться test_api_v1_clients.
    db.session.rollback()
    db.session.delete(db.session.merge(user))
    db.session.commit()


@pytest.fixture
def course():
    c = Course(title=f'Курс {_uid()}', slug=f'ordms-{_uid()}', is_active=True)
    db.session.add(c)
    db.session.commit()
    yield c
    db.session.rollback()
    db.session.delete(db.session.merge(c))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _select_tag(body, field_id):
    """Тег <select ...> цілком -- WTForms сортує атрибути за іменем, тож
    `data-*` стоїть ДО `id=` (алфавіт: 'd' < 'i'). Різка від `id="..."` до
    найближчого `>` це відрізає й мовчки ловить фальш-негатив -- знайдено
    вручну під час RED-прогону цього тесту."""
    match = re.search(r'<select\b[^>]*\bid="%s"[^>]*>' % re.escape(field_id), body)
    assert match, f'select#{field_id} не знайдено в відповіді'
    return match.group()


def test_catalog_shows_ordered_multiselect(client, admin):
    _login(client, admin)
    response = client.get('/admin/design-system')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'admin-multiselect__chip-move' in body


def test_catalog_marks_first_chip_as_primary(client, admin):
    _login(client, admin)
    response = client.get('/admin/design-system')
    body = response.get_data(as_text=True)
    assert 'admin-multiselect__chip--primary' in body


def test_course_form_enables_ordering_for_trainers(client, admin, course):
    _login(client, admin)
    response = client.get(f'/admin/courses/{course.id}/edit')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-multiselect-ordered' in _select_tag(body, 'trainer_ids')


def test_course_form_keeps_specialties_unordered(client, admin, course):
    """Спеціальності доти сенсу не мали й лишаються без кнопок переставлення."""
    _login(client, admin)
    response = client.get(f'/admin/courses/{course.id}/edit')
    body = response.get_data(as_text=True)
    assert 'data-multiselect-ordered' not in _select_tag(body, 'bpr_specialty_codes')
