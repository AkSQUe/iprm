"""Збереження переліку тренерів ПРОВЕДЕННЯ через адмінську форму.

Дзеркало tests/test_routes/test_admin_course_trainers.py, але для
CourseInstance: тут є друга умова, якої немає в курсу -- порожній вибір не
просто "очищає список", а перемикає проведення на успадкування тренерів
курсу (CourseInstance.effective_trainers). Помилка легко ховається: якщо
GET-форма редагування колись почне префілитись з effective_trainers замість
instance.trainers, збереження без змін мовчки перетворить успадкування на
явну копію -- і це має ловитись тут, а не виявлятись постфактум на проді.
"""
import re
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.models.user import User
from app.services import trainer_links


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'itr-{uuid4().hex[:6]}@test.com', 'password123',
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


def _instance(course):
    inst = CourseInstance(course_id=course.id, status='draft', event_format='offline')
    db.session.add(inst)
    db.session.commit()
    return inst


def _post(client, instance, trainer_ids):
    return client.post(f'/admin/instances/{instance.id}/edit', data={
        'course_id': str(instance.course_id),
        'start_date': '2026-01-15T10:00',
        'event_format': 'offline',
        'status': 'draft',
        'trainer_ids': [str(i) for i in trainer_ids],
    }, follow_redirects=True)


def _trainer_select_block(html):
    """Витяг <select id="trainer_ids">...</select> з HTML сторінки форми."""
    match = re.search(
        r'<select[^>]*id="trainer_ids"[^>]*>(.*?)</select>', html, re.DOTALL,
    )
    assert match, 'у формі немає select#trainer_ids'
    return match.group(1)


def test_post_saves_instances_own_trainers_in_submitted_order(client, admin, trainers):
    _login(client, admin)
    course = _course()
    instance = _instance(course)
    second, first = trainers[1], trainers[0]

    # Порядок сабміту -- спадний за id, а не алфавіт чи зростання: якщо
    # реалізація колись почне сортувати ids, цей тест на це і впаде.
    response = _post(client, instance, [second.id, first.id])
    assert response.status_code == 200

    saved = db.session.get(CourseInstance, instance.id)
    assert [t.id for t in saved.trainers] == [second.id, first.id]


def test_get_edit_form_does_not_prefill_inherited_course_trainers(client, admin, trainers):
    _login(client, admin)
    course = _course()
    trainer_links.set_trainers(course, [t.id for t in trainers])
    db.session.commit()

    # Проведення БЕЗ власних тренерів -- effective_trainers у нього вже
    # непорожній (успадкований від курсу), але instance.trainers лишається
    # []. Поле форми має відображати саме instance.trainers.
    instance = _instance(course)
    assert instance.trainers == []
    assert [t.id for t in instance.effective_trainers] == [t.id for t in trainers]

    html = client.get(f'/admin/instances/{instance.id}/edit').get_data(as_text=True)
    select_block = _trainer_select_block(html)
    assert 'selected' not in select_block


def _selected_trainer_ids(select_block):
    """Значення <option selected> -- те, що реально відправив би браузер."""
    ids = set()
    for opt in re.findall(r'<option[^>]*>', select_block):
        if 'selected' in opt:
            m = re.search(r'value="(\d+)"', opt)
            if m:
                ids.add(int(m.group(1)))
    return ids


def test_get_then_post_preserves_deactivated_linked_trainer(client, admin, trainers):
    """Дзеркало однойменного тесту для курсу (test_admin_course_trainers.py):
    деактивований, але вже прив'язаний до ПРОВЕДЕННЯ тренер має пережити
    збереження форми. populate_trainer_choices бере лише is_active=True;
    без linked_ids деактивований тренер не отримує <option> зовсім, GET-форма
    його не відправляє, і наступний set_trainers() тихо прибирає його з
    проведення."""
    _login(client, admin)
    course = _course()
    instance = _instance(course)
    a, b = trainers
    trainer_links.set_trainers(instance, [a.id, b.id])
    b.is_active = False
    db.session.commit()

    html = client.get(f'/admin/instances/{instance.id}/edit').get_data(as_text=True)
    select_block = _trainer_select_block(html)
    selected = _selected_trainer_ids(select_block)
    assert selected == {a.id, b.id}

    response = _post(client, instance, selected)
    assert response.status_code == 200
    saved = db.session.get(CourseInstance, instance.id)
    assert {t.id for t in saved.trainers} == {a.id, b.id}


def test_post_empty_selection_clears_own_list_and_falls_back_to_course(client, admin, trainers):
    _login(client, admin)
    course = _course()
    trainer_links.set_trainers(course, [t.id for t in trainers])
    db.session.commit()

    instance = _instance(course)
    trainer_links.set_trainers(instance, [trainers[0].id])
    db.session.commit()

    response = _post(client, instance, [])
    assert response.status_code == 200

    saved = db.session.get(CourseInstance, instance.id)
    # Власний перелік очищено...
    assert saved.trainers == []
    # ...а effective_trainers тепер знову дає курсовий (успадкування, а не
    # "проведення без тренера взагалі").
    assert [t.id for t in saved.effective_trainers] == [t.id for t in trainers]
