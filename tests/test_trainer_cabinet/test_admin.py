from app.extensions import db
from app.models.trainer import Trainer
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_profile import TrainerProfile
from tests.support.rbac import make_super_admin, make_user_with_role
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _admin(client):
    admin = make_super_admin(email='tc-admin@test.com')
    db.session.commit()
    login(client, admin)
    return admin


def _form(trainer, **over):
    data = {'full_name': trainer.full_name, 'slug': trainer.slug, 'is_active': 'y',
            'account_email': ''}
    data.update(over)
    return data


def test_link_account_by_email(client):
    _admin(client)
    trainer = make_trainer()
    user = make_user()
    client.post(f'/admin/trainers/{trainer.id}/edit', data=_form(trainer, account_email=user.email))
    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).user_id == user.id


def test_link_account_by_email_ignores_case(client):
    """C18: users.email завжди в нижньому регістрі (User.__init__), тож
    пошук -- прямою рівністю; регістр у введеній адміном адресі все одно
    не має заважати знайти акаунт."""
    _admin(client)
    trainer = make_trainer()
    user = make_user()
    client.post(f'/admin/trainers/{trainer.id}/edit',
               data=_form(trainer, account_email=user.email.upper()))
    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).user_id == user.id


def test_link_unknown_email_rejected(client):
    _admin(client)
    trainer = make_trainer()
    resp = client.post(f'/admin/trainers/{trainer.id}/edit',
                       data=_form(trainer, account_email='tc-nobody@test.com'))
    assert 'не знайдено' in resp.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).user_id is None


def test_link_taken_account_rejected(client):
    _admin(client)
    user = make_user()
    make_trainer(user, name='Перший')
    second = make_trainer(name='Другий')
    resp = client.post(f'/admin/trainers/{second.id}/edit',
                       data=_form(second, account_email=user.email))
    assert 'вже прив' in resp.get_data(as_text=True)


def test_unlink_with_empty_email(client):
    _admin(client)
    trainer = make_trainer(make_user())
    client.post(f'/admin/trainers/{trainer.id}/edit', data=_form(trainer))
    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).user_id is None


def _profile(trainer):
    p = TrainerProfile(trainer_id=trainer.id, full_name='Іваненко')
    p.fop_iban = 'UA213052990000026003006239637'
    db.session.add(p)
    db.session.commit()
    return p


def test_questionnaire_reveals_for_manage(client):
    _admin(client)
    trainer = make_trainer(make_user())
    _profile(trainer)
    html = client.get(f'/admin/trainers/{trainer.id}/questionnaire').get_data(as_text=True)
    assert 'UA213052990000026003006239637' in html


def test_questionnaire_masks_for_view_only(client):
    viewer = make_user_with_role('viewer', email='tc-viewer@test.com')
    db.session.commit()
    login(client, viewer)
    trainer = make_trainer(make_user())
    _profile(trainer)
    resp = client.get(f'/admin/trainers/{trainer.id}/questionnaire')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'UA213052990000026003006239637' not in html
    assert '•••• 9637' in html


def _submitted(trainer):
    p = TrainerCourseProposal(trainer_id=trainer.id, title='КОС', theses=['a'],
                              status='submitted')
    db.session.add(p)
    db.session.commit()
    return p


def test_accept_and_return(client):
    _admin(client)
    trainer = make_trainer(make_user())
    p = _submitted(trainer)
    client.post(f'/admin/trainers/proposals/{p.id}/return', data={f'p{p.id}-comment': 'Уточніть'})
    db.session.expire_all()
    assert p.status == 'draft' and p.curator_comment == 'Уточніть'
    p.status = 'submitted'
    db.session.commit()
    client.post(f'/admin/trainers/proposals/{p.id}/accept')
    db.session.expire_all()
    assert p.status == 'accepted'
    resp = client.post(f'/admin/trainers/proposals/{p.id}/accept', follow_redirects=True)
    assert 'Неможливо' in resp.get_data(as_text=True)


def test_list_indicators(client):
    _admin(client)
    trainer = make_trainer(make_user(), name='Індикаторний')
    _submitted(trainer)
    html = client.get('/admin/trainers').get_data(as_text=True)
    assert 'data-trainer-linked="' + str(trainer.id) + '"' in html
    assert 'data-trainer-new-proposals="' + str(trainer.id) + '"' in html
    # C15: бейдж-число без підпису скрінрідер озвучує як голе "1".
    assert 'aria-label="Нових пропозицій: 1"' in html


# --- A1: фінансові й персональні дані лише з trainers.finance ---------------

_IBAN = 'UA213052990000026003006239637'


def _full_profile(trainer):
    from datetime import date
    p = TrainerProfile(trainer_id=trainer.id, full_name='Іваненко Петро',
                       phone='+380671112233', birth_date=date(1980, 5, 17),
                       registration_address='вул. Секретна, 7, Київ',
                       edrpou='31234567')
    p.fop_iban = _IBAN
    p.tax_id = '3123456789'
    db.session.add(p)
    db.session.commit()
    return p


def _role_user(*perms):
    """Користувач зі своєю роллю з рівно цими правами (не системною)."""
    from uuid import uuid4

    from app.models.rbac import Permission, Role
    role = Role(name=f'tc_fin_{uuid4().hex[:6]}', display_name='T')
    db.session.add(role)
    for name in perms:
        role.permissions.append(Permission.query.filter_by(name=name).one())
    db.session.flush()
    user = make_user_with_role(role.name, email=f'tc-fin-{uuid4().hex[:6]}@test.com')
    db.session.commit()
    return user


def _questionnaire_as(client, user):
    login(client, user)
    trainer = make_trainer(make_user())
    _full_profile(trainer)
    resp = client.get(f'/admin/trainers/{trainer.id}/questionnaire')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _assert_finance_hidden(html):
    assert _IBAN not in html
    assert '3123456789' not in html
    assert '•••• 9637' in html
    assert '17.05.1980' not in html
    assert 'вул. Секретна' not in html
    assert '31234567' not in html
    # Контакти куратору потрібні -- їх видно й без finance.
    assert 'Іваненко Петро' in html
    assert '+380671112233' in html
    assert 'Тренери: Фінансові реквізити' in html


def _assert_finance_shown(html):
    assert _IBAN in html
    assert '3123456789' in html
    assert '17.05.1980' in html
    assert 'вул. Секретна' in html
    assert '31234567' in html


def test_questionnaire_content_editor_sees_no_finance(client):
    editor = make_user_with_role('content_editor', email='tc-editor@test.com')
    db.session.commit()
    _assert_finance_hidden(_questionnaire_as(client, editor))


def test_questionnaire_manage_alone_does_not_reveal(client):
    _assert_finance_hidden(_questionnaire_as(client, _role_user('trainers.view', 'trainers.manage')))


def test_questionnaire_viewer_sees_no_finance(client):
    viewer = make_user_with_role('viewer', email='tc-viewer2@test.com')
    db.session.commit()
    _assert_finance_hidden(_questionnaire_as(client, viewer))


def test_questionnaire_finance_role_sees_everything(client):
    _assert_finance_shown(_questionnaire_as(client, _role_user('trainers.view', 'trainers.finance')))


def test_questionnaire_super_admin_sees_everything(client):
    admin = make_super_admin(email='tc-sa2@test.com')
    db.session.commit()
    _assert_finance_shown(_questionnaire_as(client, admin))


def test_content_editor_can_still_curate_without_finance(client):
    editor = make_user_with_role('content_editor', email='tc-editor2@test.com')
    db.session.commit()
    login(client, editor)
    trainer = make_trainer(make_user())
    p = _submitted(trainer)
    client.post(f'/admin/trainers/proposals/{p.id}/accept')
    db.session.expire_all()
    assert p.status == 'accepted'


# --- A2: неперевірений email не прив'язується ---------------------------------

def test_link_unconfirmed_account_rejected(client):
    _admin(client)
    trainer = make_trainer()
    user = make_user()
    user.email_confirmed = False
    db.session.commit()
    resp = client.post(f'/admin/trainers/{trainer.id}/edit',
                       data=_form(trainer, account_email=user.email))
    assert 'ще не підтвердив email' in resp.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).user_id is None


def test_resave_keeps_existing_link_even_if_unconfirmed(client):
    """Правка картки з тим самим акаунтом не має блокуватися: прив'язку
    зроблено раніше, а доступ до кабінету все одно закриває декоратор."""
    _admin(client)
    user = make_user()
    trainer = make_trainer(user)
    user.email_confirmed = False
    db.session.commit()
    client.post(f'/admin/trainers/{trainer.id}/edit',
                data=_form(trainer, account_email=user.email, full_name='Нове імʼя'))
    db.session.expire_all()
    saved = db.session.get(Trainer, trainer.id)
    assert saved.user_id == user.id
    assert saved.full_name == 'Нове імʼя'


# --- B5: прив'язка й відв'язка акаунта -- в аудит ------------------------------

import logging  # noqa: E402


def _audit(caplog):
    return [r.getMessage() for r in caplog.records if r.name == 'audit']


def test_link_is_audited(client, caplog):
    admin = _admin(client)
    trainer = make_trainer()
    user = make_user()
    with caplog.at_level(logging.INFO, logger='audit'):
        client.post(f'/admin/trainers/{trainer.id}/edit',
                    data=_form(trainer, account_email=user.email))
    assert (f'Admin {admin.email} linked user {user.id} to trainer {trainer.id} (was None)'
            in _audit(caplog))


def test_relink_is_audited_with_previous_user(client, caplog):
    admin = _admin(client)
    old = make_user()
    trainer = make_trainer(old)
    new = make_user()
    with caplog.at_level(logging.INFO, logger='audit'):
        client.post(f'/admin/trainers/{trainer.id}/edit',
                    data=_form(trainer, account_email=new.email))
    assert (f'Admin {admin.email} linked user {new.id} to trainer {trainer.id} (was {old.id})'
            in _audit(caplog))


def test_unlink_is_audited(client, caplog):
    admin = _admin(client)
    user = make_user()
    trainer = make_trainer(user)
    with caplog.at_level(logging.INFO, logger='audit'):
        client.post(f'/admin/trainers/{trainer.id}/edit', data=_form(trainer))
    assert (f'Admin {admin.email} unlinked user {user.id} from trainer {trainer.id}'
            in _audit(caplog))


def test_unchanged_link_not_audited(client, caplog):
    _admin(client)
    user = make_user()
    trainer = make_trainer(user)
    with caplog.at_level(logging.INFO, logger='audit'):
        client.post(f'/admin/trainers/{trainer.id}/edit',
                    data=_form(trainer, account_email=user.email))
    assert not [m for m in _audit(caplog) if 'linked user' in m]


def test_create_with_link_is_audited(client, caplog):
    admin = _admin(client)
    user = make_user()
    from uuid import uuid4
    slug = f'tc-{uuid4().hex[:10]}'
    with caplog.at_level(logging.INFO, logger='audit'):
        client.post('/admin/trainers/new', data={
            'full_name': 'Новий Т.', 'slug': slug, 'is_active': 'y',
            'account_email': user.email})
    trainer = Trainer.query.filter_by(slug=slug).one()
    assert (f'Admin {admin.email} linked user {user.id} to trainer {trainer.id} (was None)'
            in _audit(caplog))


# --- B8: прийняття можна скасувати -----------------------------------------------

def test_unaccept_returns_to_review(client, caplog):
    _admin(client)
    trainer = make_trainer(make_user())
    p = _submitted(trainer)
    p.status = 'accepted'
    db.session.commit()
    with caplog.at_level(logging.INFO, logger='audit'):
        resp = client.post(f'/admin/trainers/proposals/{p.id}/unaccept')
    assert resp.status_code == 302
    db.session.expire_all()
    assert p.status == 'submitted'
    assert any('unaccepted trainer proposal' in m for m in _audit(caplog))
    resp = client.post(f'/admin/trainers/proposals/{p.id}/unaccept', follow_redirects=True)
    assert 'Неможливо' in resp.get_data(as_text=True)


def test_unaccept_requires_manage(client):
    viewer = _role_user('trainers.view')
    trainer = make_trainer(make_user())
    p = _submitted(trainer)
    p.status = 'accepted'
    db.session.commit()
    login(client, viewer)
    resp = client.post(f'/admin/trainers/proposals/{p.id}/unaccept')
    assert resp.status_code in (302, 403)
    db.session.expire_all()
    assert p.status == 'accepted'


def test_accept_and_unaccept_buttons_ask_confirmation(client):
    _admin(client)
    trainer = make_trainer(make_user())
    p = _submitted(trainer)
    html = client.get(f'/admin/trainers/{trainer.id}/questionnaire').get_data(as_text=True)
    accept_action = f'/admin/trainers/proposals/{p.id}/accept'
    form_tag = html[html.rindex('<form', 0, html.index(accept_action)):html.index(accept_action) + 200]
    assert 'data-confirm=' in form_tag
    p.status = 'accepted'
    db.session.commit()
    html = client.get(f'/admin/trainers/{trainer.id}/questionnaire').get_data(as_text=True)
    unaccept_action = f'/admin/trainers/proposals/{p.id}/unaccept'
    assert unaccept_action in html
    form_tag = html[html.rindex('<form', 0, html.index(unaccept_action)):html.index(unaccept_action) + 200]
    assert 'data-confirm=' in form_tag
    assert 'Скасувати прийняття' in html


# --- C15: доступність форми повернення на доопрацювання --------------------

def _second_trainer_proposal(trainer, title='Другий курс'):
    p = TrainerCourseProposal(trainer_id=trainer.id, title=title, theses=['a'],
                              status='submitted')
    db.session.add(p)
    db.session.commit()
    return p


def test_two_submitted_proposals_have_distinct_comment_fields(client):
    """Раніше return_form був ОДИН на всю сторінку -- дві форми повернення
    рендерили textarea з однаковими name/id (невалідний HTML, і submit
    будь-якої форми ніс те саме поле)."""
    _admin(client)
    trainer = make_trainer(make_user())
    p1 = _submitted(trainer)
    p2 = _second_trainer_proposal(trainer)
    html = client.get(f'/admin/trainers/{trainer.id}/questionnaire').get_data(as_text=True)
    name1, name2 = f'name="p{p1.id}-comment"', f'name="p{p2.id}-comment"'
    assert name1 in html and name2 in html
    assert name1 != name2


def test_return_binds_correct_proposal_among_several(client):
    _admin(client)
    trainer = make_trainer(make_user())
    p1 = _submitted(trainer)
    p2 = _second_trainer_proposal(trainer)
    client.post(f'/admin/trainers/proposals/{p2.id}/return',
               data={f'p{p2.id}-comment': 'Доопрацюйте другий'})
    db.session.expire_all()
    assert p2.status == 'draft' and p2.curator_comment == 'Доопрацюйте другий'
    assert p1.status == 'submitted' and p1.curator_comment is None


def test_return_textarea_has_visible_label(client):
    """Скрінрідер має озвучити ЩО за поле -- не просто "текстове поле"."""
    _admin(client)
    trainer = make_trainer(make_user())
    p = _submitted(trainer)
    html = client.get(f'/admin/trainers/{trainer.id}/questionnaire').get_data(as_text=True)
    field_id = f'p{p.id}-comment'
    assert f'for="{field_id}"' in html
    label_pos = html.index(f'for="{field_id}"')
    label_tag = html[html.rindex('<label', 0, label_pos):html.index('</label>', label_pos)]
    assert 'visually-hidden' in label_tag
    assert 'Коментар для тренера' in label_tag
