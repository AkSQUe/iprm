"""Три нові кнопки "з картки -- у свій зріз": instance_edit -> реєстрації
проведення, trainer_edit -> курси тренера, course_edit -> розклад курсу.

Жодна з трьох цільових реєстрів (instance_registrations, courses_list,
instances_list) не має нетривіального дефолту, що ховає рядки картки без
додаткового параметра (на відміну від registrations_all зі scope='upcoming',
який user_detail.html вже нейтралізує) -- перевірено читанням
app/admin/routes_registrations.py, routes_courses.py, routes_instances.py.
Тому лінкам досить лише свого id-фільтра; сторож усе одно пінить URL через
справжній url_for, щоб зміна дефолту в майбутньому впала тут, а не мовчки.
"""
import re
from uuid import uuid4

import pytest
from flask import url_for

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'cbl-{_uid()}@test.com', 'password123',
        first_name='C', last_name='B', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


# --- instance_edit.html: реєстрації цього проведення ------------------------

def test_instance_edit_links_to_its_own_registrations(client, admin, app):
    course = Course(title=f'Картка {_uid()}', slug=f'cbl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
    )
    db.session.add(inst)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/instances/{inst.id}/edit').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.instance_registrations', instance_id=inst.id)
        assert re.search(
            rf'<a href="{re.escape(href)}" class="btn-admin btn-admin--secondary">'
            r'.*?Реєстрації', html, re.DOTALL,
        )
    finally:
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.commit()


# --- trainer_edit.html: курси цього тренера ----------------------------------

def test_trainer_edit_links_to_courses_by_trainer_id(client, admin, app):
    trainer = Trainer(full_name=f'Тренер {_uid()}', slug=f'cbl-{_uid()}')
    db.session.add(trainer)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/trainers/{trainer.id}/edit').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.courses_list', trainer_id=trainer.id)
        assert re.search(
            rf'<a href="{re.escape(href)}" class="btn-admin btn-admin--secondary">'
            r'.*?Курси', html, re.DOTALL,
        )
    finally:
        db.session.delete(db.session.merge(trainer))
        db.session.commit()


# --- course_edit.html: розклад цього курсу (реєстр, не таблиця поруч) -------

def test_course_edit_links_to_instances_by_course_id(client, admin, app):
    course = Course(title=f'Картка {_uid()}', slug=f'cbl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/courses/{course.id}/edit').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.instances_list', course_id=course.id)
        assert re.search(
            rf'<a href="{re.escape(href)}" class="btn-admin btn-admin--secondary">'
            r'.*?Розклад', html, re.DOTALL,
        )
    finally:
        db.session.delete(db.session.merge(course))
        db.session.commit()
