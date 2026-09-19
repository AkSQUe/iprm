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
    client.post(f'/admin/trainers/proposals/{p.id}/return', data={'comment': 'Уточніть'})
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
    assert 'data-trainer-new-proposals="' + str(trainer.id) + '">1<' in html
