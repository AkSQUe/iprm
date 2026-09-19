from app.extensions import db
from app.models.trainer_course_proposal import TrainerCourseProposal
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user

DATA = {
    'title': 'КОС крові: діагностика',
    'theses': 'Методи визначення КОС\nФізіологічні межі рН\nБуферні системи',
    'language': 'Українська',
    'relevance': 'Лікарю важливо це знати, тому що...',
    'target_specialties': 'Анестезіологи, хірурги',
    'resources': '', 'future_topics': '', 'quiz_url': '',
}


def _setup(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    return trainer


def test_create_draft(client):
    trainer = _setup(client)
    resp = client.post('/trainer/proposals/new', data=DATA)
    assert resp.status_code == 302
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    assert p.status == 'draft'
    assert p.theses == ['Методи визначення КОС', 'Фізіологічні межі рН', 'Буферні системи']


def test_title_limit_and_theses_limit(client):
    _setup(client)
    resp = client.post('/trainer/proposals/new', data={**DATA, 'title': 'x' * 51})
    assert resp.status_code == 200 and 'form-error' in resp.get_data(as_text=True)
    resp = client.post('/trainer/proposals/new',
                       data={**DATA, 'theses': '\n'.join(str(i) for i in range(11))})
    assert resp.status_code == 200 and 'form-error' in resp.get_data(as_text=True)
    resp = client.post('/trainer/proposals/new', data={**DATA, 'theses': '  \n '})
    assert resp.status_code == 200 and 'form-error' in resp.get_data(as_text=True)


def test_submit_locks_editing(client):
    trainer = _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    assert client.post(f'/trainer/proposals/{p.id}/submit').status_code == 302
    db.session.expire_all()
    assert p.status == 'submitted'
    resp = client.post(f'/trainer/proposals/{p.id}', data={**DATA, 'title': 'Інше'})
    assert resp.status_code == 409
    assert client.post(f'/trainer/proposals/{p.id}/delete').status_code == 409
    view = client.get(f'/trainer/proposals/{p.id}').get_data(as_text=True)
    assert 'КОС крові: діагностика' in view and 'name="title"' not in view


def test_delete_draft(client):
    trainer = _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    assert client.post(f'/trainer/proposals/{p.id}/delete').status_code == 302
    assert TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).count() == 0


def test_foreign_proposal_is_404(client):
    owner = make_trainer(make_user(), name='Власник')
    p = TrainerCourseProposal(trainer_id=owner.id, title='Чуже', theses=['a'])
    db.session.add(p)
    db.session.commit()
    _setup(client)
    assert client.get(f'/trainer/proposals/{p.id}').status_code == 404
    assert client.post(f'/trainer/proposals/{p.id}/submit').status_code == 404
    assert client.post(f'/trainer/proposals/{p.id}/delete').status_code == 404


def test_profile_page_lists_proposals(client):
    _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    html = client.get('/trainer/profile').get_data(as_text=True)
    assert 'КОС крові: діагностика' in html
