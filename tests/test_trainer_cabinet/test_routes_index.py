from app.extensions import db
from app.services.trainer_links import set_trainers
from tests.support.rbac import make_super_admin
from tests.test_trainer_cabinet._factories import (
    login, make_course, make_instance, make_registration, make_trainer, make_user,
)


def test_anonymous_redirected_to_login(client):
    resp = client.get('/trainer/')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_user_without_card_gets_404(client):
    login(client, make_user())
    assert client.get('/trainer/').status_code == 404


def test_staff_without_card_gets_404(client):
    admin = make_super_admin(email='tc-admin@test.com')
    db.session.commit()
    login(client, admin)
    assert client.get('/trainer/').status_code == 404


def test_inactive_card_gets_404(client):
    user = make_user()
    make_trainer(user, is_active=False)
    login(client, user)
    assert client.get('/trainer/').status_code == 404


def test_dashboard_shows_event_and_counts(client):
    user = make_user()
    trainer = make_trainer(user)
    course = make_course('Кислотно-основний стан')
    set_trainers(course, [trainer.id])
    db.session.commit()
    inst = make_instance(course, max_participants=15)
    make_registration(inst, payment_status='paid')
    make_registration(inst)
    login(client, user)
    resp = client.get('/trainer/')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'Кислотно-основний стан' in html
    assert 'data-count="total">2<' in html
    assert 'data-count="paid">1<' in html
    assert 'data-count="capacity">15<' in html
    assert '/trainer/profile' in html and '/trainer/contract' in html and '/trainer/faq' in html
    assert resp.headers.get('X-Robots-Tag') == 'noindex, nofollow'


def test_dashboard_empty_state(client):
    user = make_user()
    make_trainer(user)
    login(client, user)
    html = client.get('/trainer/').get_data(as_text=True)
    assert 'iprm-empty-state' in html


def test_faq_page(client):
    user = make_user()
    make_trainer(user)
    login(client, user)
    resp = client.get('/trainer/faq')
    assert resp.status_code == 200
    assert 'Типовий розклад заходу' in resp.get_data(as_text=True)


def test_header_link_only_for_trainer(client):
    user = make_user()
    login(client, user)
    assert '/trainer/' not in client.get('/auth/account').get_data(as_text=True)
    make_trainer(user)
    db.session.expire(user)
    assert '/trainer/' in client.get('/auth/account').get_data(as_text=True)


def test_unconfirmed_email_gets_404_and_no_header_link(client):
    user = make_user()
    make_trainer(user)
    user.email_confirmed = False
    db.session.commit()
    login(client, user)
    assert client.get('/trainer/').status_code == 404
    assert '/trainer/' not in client.get('/auth/account').get_data(as_text=True)
