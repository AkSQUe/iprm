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


# --- картка: живі контакти й переноси рядків -------------------------------

def _class_chain_of(html, needle):
    """Класи всіх елементів, усередині яких стоїть needle (від кореня до нього)."""
    from html.parser import HTMLParser

    class _Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.found = [], None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if self.found is None and tag == 'a' and needle in (attrs.get('href') or ''):
                self.found = [cls for _, cls in self.stack] + [attrs.get('class') or '']
            if tag not in ('br', 'img', 'input', 'meta', 'link', 'hr'):
                self.stack.append((tag, attrs.get('class') or ''))

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break

    parser = _Parser()
    parser.feed(html)
    return parser.found


def test_contact_links_are_clickable(client, admin, application):
    """.admin-field-readonly має pointer-events: none -- посилання в ньому мертві."""
    switch_user(client, admin)
    html = client.get(f'/admin/trainer-applications/{application.id}').get_data(as_text=True)
    for needle in ('tel:+380671112233', f'mailto:{application.email}'):
        chain = _class_chain_of(html, needle)
        assert chain is not None, needle
        assert not any('admin-field-readonly' in cls.split() for cls in chain), needle


def test_multiline_answers_keep_line_breaks(client, admin, application):
    application.workplace = 'Клініка А\nКлініка Б'
    application.topic = 'Перша тема\nДруга тема'
    db.session.commit()
    switch_user(client, admin)
    html = client.get(f'/admin/trainer-applications/{application.id}').get_data(as_text=True)
    assert 'admin-multiline">Клініка А\nКлініка Б<' in html
    assert 'admin-multiline">Перша тема\nДруга тема<' in html


def test_multiline_text_is_escaped(client, admin, application):
    application.topic = '<script>alert(1)</script>'
    db.session.commit()
    switch_user(client, admin)
    html = client.get(f'/admin/trainer-applications/{application.id}').get_data(as_text=True)
    assert '<script>alert(1)</script>' not in html


# --- «Створити тренера»: потрібні ОБИДВА права ------------------------------

@pytest.mark.parametrize('role', ['manager', 'content_editor'])
def test_create_trainer_needs_both_permissions(client, application, role):
    """manager має лише trainer_applications.*, content_editor -- лише trainers.manage."""
    application.status = 'approved'
    db.session.commit()
    user = make_user_with_role(role)
    db.session.commit()
    switch_user(client, user)
    count = Trainer.query.count()
    resp = client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    assert resp.status_code == 403
    db.session.refresh(application)
    assert application.trainer_id is None
    assert Trainer.query.count() == count


def test_manager_sees_no_create_button(client, application):
    application.status = 'approved'
    db.session.commit()
    user = make_user_with_role('manager')
    db.session.commit()
    switch_user(client, user)
    resp = client.get(f'/admin/trainer-applications/{application.id}')
    assert resp.status_code == 200
    assert 'create-trainer' not in resp.get_data(as_text=True)


# --- аудит автоприв'язки акаунта -------------------------------------------

def _audit(caplog):
    return [r.getMessage() for r in caplog.records if r.name == 'audit']


def test_auto_linked_account_is_audited(client, admin, application, caplog):
    import logging
    from app.models.user import User
    user = User.create_with_password(application.email, 'password123', first_name='О',
                                     last_name='П', email_confirmed=True)
    application.status = 'approved'
    db.session.commit()
    switch_user(client, admin)
    with caplog.at_level(logging.INFO, logger='audit'):
        client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    db.session.refresh(application)
    trainer = db.session.get(Trainer, application.trainer_id)
    assert trainer.user_id == user.id
    assert (f'Admin {admin.email} linked user {user.id} to trainer {trainer.id} (was None)'
            in _audit(caplog))


def test_no_account_no_link_audit(client, admin, application, caplog):
    import logging
    application.status = 'approved'
    db.session.commit()
    switch_user(client, admin)
    with caplog.at_level(logging.INFO, logger='audit'):
        client.post(f'/admin/trainer-applications/{application.id}/create-trainer')
    assert not [m for m in _audit(caplog) if 'linked user' in m]


def test_email_preview_has_own_trigger(client, admin):
    switch_user(client, admin)
    html = client.get('/admin/notifications/templates').get_data(as_text=True)
    start = html.index('<strong>Шаблон:</strong> trainer_application_notification.html')
    trigger_line = html[start:].split('<strong>Тригер:</strong>', 1)[1].split('</span>', 1)[0]
    assert trigger_line.strip() == 'trainer_application'
