"""Збереження переліку тренерів курсу через адмінську форму."""
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.trainer import Trainer
from app.models.user import User


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'tr-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    # Прибираємо за собою: інакше валиться test_api_v1_clients.
    db.session.delete(user)
    db.session.commit()


@pytest.fixture
def trainers():
    rows = [
        Trainer(full_name='Андрієнко А.', slug=uuid4().hex[:8], is_active=True),
        Trainer(full_name='Богданенко Б.', slug=uuid4().hex[:8], is_active=True),
    ]
    db.session.add_all(rows)
    db.session.commit()
    return rows


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _course():
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=uuid4().hex[:8])
    db.session.add(course)
    db.session.commit()
    return course


def _post(client, course, trainer_ids):
    return client.post(f'/admin/courses/{course.id}/edit', data={
        'title': course.title, 'slug': course.slug, 'event_type': 'seminar',
        'trainer_ids': [str(i) for i in trainer_ids],
    }, follow_redirects=True)


def test_saves_submitted_order_as_is(client, admin, trainers):
    _login(client, admin)
    course = _course()
    second, first = trainers[1], trainers[0]
    assert _post(client, course, [second.id, first.id]).status_code == 200
    saved = db.session.get(Course, course.id)
    # Порядок сабміту, а не алфавіт: перший у списку -- головний лектор.
    assert [t.id for t in saved.trainers] == [second.id, first.id]


def test_reordering_rewrites_positions(client, admin, trainers):
    _login(client, admin)
    course = _course()
    a, b = trainers
    _post(client, course, [a.id, b.id])
    _post(client, course, [b.id, a.id])
    assert [t.id for t in db.session.get(Course, course.id).trainers] == [b.id, a.id]


def test_empty_submission_clears_the_list(client, admin, trainers):
    _login(client, admin)
    course = _course()
    _post(client, course, [trainers[0].id])
    _post(client, course, [])
    assert db.session.get(Course, course.id).trainers == []


def _selected_trainer_ids(html):
    """Значення, що їх ЖИВИЙ браузер відправив би для trainer_ids: лише
    <option selected> -- WTForms малює selected тільки для значень, наявних
    у choices, тож деактивований тренер без linked_ids узагалі випав би з
    розмітки, а не просто лишився невибраним."""
    select = BeautifulSoup(html, 'html.parser').find(id='trainer_ids')
    return {int(opt['value']) for opt in select.find_all('option') if opt.has_attr('selected')}


def test_get_then_post_preserves_deactivated_linked_trainer(client, admin, trainers):
    """Деактивований, але вже прив'язаний тренер має пережити збереження
    форми -- навіть коли сабміт міняє геть інше поле. populate_trainer_choices
    бере лише is_active=True; без linked_ids деактивований тренер не
    отримує <option> зовсім, GET-форма його не відправляє, і наступний
    set_trainers() тихо прибирає його з курсу."""
    _login(client, admin)
    course = _course()
    a, b = trainers
    from app.services import trainer_links
    trainer_links.set_trainers(course, [a.id, b.id])
    b.is_active = False
    db.session.commit()

    resp = client.get(f'/admin/courses/{course.id}/edit')
    assert resp.status_code == 200
    selected = _selected_trainer_ids(resp.data)
    assert selected == {a.id, b.id}

    resp = _post(client, course, selected)
    assert resp.status_code == 200
    saved = db.session.get(Course, course.id)
    assert {t.id for t in saved.trainers} == {a.id, b.id}


def test_duplicate_copies_trainers_with_order(client, admin, trainers):
    from app.services import course_service

    course = _course()
    a, b = trainers
    from app.services import trainer_links
    trainer_links.set_trainers(course, [b.id, a.id])
    db.session.commit()
    clone = course_service.clone_course(course, created_by_id=admin.id)
    db.session.commit()
    assert [t.id for t in clone.trainers] == [b.id, a.id]
