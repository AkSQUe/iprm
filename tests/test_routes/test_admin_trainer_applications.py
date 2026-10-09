"""Адмінка заявок кандидатів у тренери."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.trainer import Trainer
from app.models.trainer_application import TrainerApplication
from tests.support.rbac import make_super_admin, make_user_with_role, switch_user


@pytest.fixture(autouse=True)
def _no_csrf(app):
    prev = app.config.get('WTF_CSRF_ENABLED')
    app.config['WTF_CSRF_ENABLED'] = False
    yield
    app.config['WTF_CSRF_ENABLED'] = prev


@pytest.fixture
def application(app):
    item = TrainerApplication(
        full_name='Петренко Олена', phone='+380671112233',
        email=f'olena-{uuid4().hex[:8]}@example.com', specialty='Гінекологія',
        topic='PRP у гінекології',
        answers=[{'key': 'plasma_years',
                  'label': 'Як давно ви використовуєте PRP- та плазмотерапію?', 'value': 'gt5'}],
    )
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def admin(app):
    user = make_super_admin()
    db.session.commit()
    return user


def test_role_without_permission_gets_403(client, application):
    # content_editor не має trainer_applications.* (RoleSpec у registry.py).
    user = make_user_with_role('content_editor')
    db.session.commit()
    switch_user(client, user)
    assert client.get('/admin/trainer-applications').status_code == 403


def test_anonymous_is_sent_away(app, application):
    resp = app.test_client().get('/admin/trainer-applications')
    assert resp.status_code in (302, 401, 403)


def test_list_shows_application(client, admin, application):
    switch_user(client, admin)
    html = client.get('/admin/trainer-applications').get_data(as_text=True)
    assert 'Петренко Олена' in html
    assert f'/admin/trainer-applications/{application.id}' in html


def test_detail_shows_answers_in_ukrainian(client, admin, application):
    switch_user(client, admin)
    html = client.get(f'/admin/trainer-applications/{application.id}').get_data(as_text=True)
    assert 'Як давно ви використовуєте PRP- та плазмотерапію?' in html
    assert 'Понад 5 років' in html
    assert 'PRP у гінекології' in html


def test_update_status_and_notes(client, admin, application):
    switch_user(client, admin)
    resp = client.post(f'/admin/trainer-applications/{application.id}/update',
                       data={'status': 'in_progress', 'admin_notes': 'Подзвонити в понеділок'})
    assert resp.status_code == 302
    db.session.refresh(application)
    assert application.status == 'in_progress'
    assert application.admin_notes == 'Подзвонити в понеділок'


def test_update_unknown_status_refused(client, admin, application):
    switch_user(client, admin)
    client.post(f'/admin/trainer-applications/{application.id}/update',
                data={'status': 'archived'})
    db.session.refresh(application)
    assert application.status == 'new'


def test_create_trainer_only_for_approved(client, admin, application):
    switch_user(client, admin)
    client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    db.session.refresh(application)
    assert application.trainer_id is None


def test_create_trainer_redirects_to_trainer_edit(client, admin, application):
    application.status = 'approved'
    db.session.commit()
    switch_user(client, admin)
    resp = client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    db.session.refresh(application)
    assert application.trainer_id is not None
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith(f'/admin/trainers/{application.trainer_id}/edit')
    trainer = db.session.get(Trainer, application.trainer_id)
    assert trainer.is_active is False


def test_second_create_does_not_duplicate(client, admin, application):
    application.status = 'approved'
    db.session.commit()
    switch_user(client, admin)
    client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    count = Trainer.query.count()
    client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    assert Trainer.query.count() == count


def test_detail_links_existing_trainer(client, admin, application):
    application.status = 'approved'
    db.session.commit()
    switch_user(client, admin)
    client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    html = client.get(f'/admin/trainer-applications/{application.id}').get_data(as_text=True)
    assert f'/admin/trainers/{application.trainer_id}/edit' in html
    assert 'create-trainer' not in html


def test_email_preview_lists_trainer_application(client, admin):
    switch_user(client, admin)
    html = client.get('/admin/notifications/templates').get_data(as_text=True)
    assert 'Заявка кандидата в тренери' in html
