"""Посилання з анкети тренера -- лише http(s).

WTForms URL() пропускає `javascript://example.com/%0aalert(1)`: схема
довільна, а `%0a` після "коментаря" `//` виконується як код у href. Тому
перевірка двошарова: форма відкидає не-http(s) схему, а шаблони виводять
href лише для http(s) або шляху сайту -- на випадок значень, що вже лежать
у базі (або потрапили туди в обхід форми).
"""
from app.extensions import db
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_profile import TrainerProfile
from tests.support.rbac import make_super_admin
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user

EVIL = 'javascript://example.com/%0aalert(1)'

PROPOSAL = {
    'title': 'КОС крові', 'theses': 'Теза', 'language': '', 'relevance': '',
    'target_specialties': '', 'resources': '', 'future_topics': '',
}


def _trainer(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    return trainer


def test_proposal_rejects_javascript_quiz_url(client):
    trainer = _trainer(client)
    resp = client.post('/trainer/proposals/new', data={**PROPOSAL, 'quiz_url': EVIL})
    assert resp.status_code == 200
    assert 'form-error' in resp.get_data(as_text=True)
    assert TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).count() == 0


def test_proposal_accepts_https_quiz_url(client):
    trainer = _trainer(client)
    url = 'https://docs.google.com/forms/d/abc'
    resp = client.post('/trainer/proposals/new', data={**PROPOSAL, 'quiz_url': url})
    assert resp.status_code == 302
    assert TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one().quiz_url == url


def test_profile_rejects_javascript_photo_url(client):
    trainer = _trainer(client)
    resp = client.post('/trainer/profile', data={'photo_url': EVIL})
    assert resp.status_code == 200
    assert 'form-error' in resp.get_data(as_text=True)
    assert TrainerProfile.query.filter_by(trainer_id=trainer.id).first() is None


def _bad_rows(trainer):
    profile = TrainerProfile(trainer_id=trainer.id, full_name='Іваненко', photo_url=EVIL)
    proposal = TrainerCourseProposal(trainer_id=trainer.id, title='КОС', theses=['a'],
                                     status='submitted', quiz_url=EVIL)
    db.session.add_all([profile, proposal])
    db.session.commit()


def test_admin_questionnaire_never_links_javascript(client):
    admin = make_super_admin(email='tc-admin-xss@test.com')
    db.session.commit()
    login(client, admin)
    trainer = make_trainer(make_user())
    _bad_rows(trainer)
    html = client.get(f'/admin/trainers/{trainer.id}/questionnaire').get_data(as_text=True)
    assert 'href="javascript:' not in html
    # Значення не ховаємо -- куратор має бачити, що саме ввів тренер.
    assert 'javascript://example.com/%0aalert(1)' in html


def test_trainer_profile_never_links_javascript(client):
    trainer = _trainer(client)
    _bad_rows(trainer)
    html = client.get('/trainer/profile').get_data(as_text=True)
    assert 'href="javascript:' not in html


def test_safe_href():
    from app.utils import safe_href
    assert safe_href('https://x.com/a') == 'https://x.com/a'
    assert safe_href('HTTP://x.com') == 'HTTP://x.com'
    assert safe_href('/media/a.webp') == '/media/a.webp'
    for bad in (EVIL, 'JavaScript:alert(1)', 'data:text/html,x', '//evil.com/x',
                ' javascript:alert(1)', '', None):
        assert safe_href(bad) == ''
