"""Публічна сторінка «Стати тренером»: рендер, анкета, заклик."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.trainer_application import TrainerApplication


def _payload(**kw):
    data = {
        'full_name': 'Іваненко Іван', 'phone': '+380501112233',
        'email': f'cand-{uuid4().hex[:8]}@example.com', 'city': 'Київ',
        'specialty': 'Дерматологія', 'workplace': '', 'social_links': '',
        'topic': 'PRP у трихології', 'consent': 'y',
        'q_plasma_years': '1_3', 'q_tubes_per_day': '6_10',
        'q_directions': 'Трихологія', 'q_equipment': '', 'q_teaching': 'none',
    }
    data.update(kw)
    return data


@pytest.fixture(autouse=True)
def _no_csrf(app):
    prev = app.config.get('WTF_CSRF_ENABLED')
    app.config['WTF_CSRF_ENABLED'] = False
    yield
    app.config['WTF_CSRF_ENABLED'] = prev


@pytest.mark.parametrize('prefix', ['', '/ru', '/en'])
def test_page_renders_in_every_language(client, prefix):
    resp = client.get(f'{prefix}/trainers/join')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="q_plasma_years"' in html
    assert 'name="consent"' in html


def test_page_shows_alyona_text_by_default(client):
    html = client.get('/trainers/join').get_data(as_text=True)
    assert 'Ваш досвід може стати цінним для інших' in html
    assert 'Виступати перед професійною аудиторією' in html


def test_submit_saves_application_and_notifies(client, monkeypatch):
    calls = []
    monkeypatch.setattr('app.services.trainer_recruitment.notify', calls.append)
    payload = _payload()
    resp = client.post('/trainers/join', data=payload)
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/trainers/join?sent=1')
    item = TrainerApplication.query.filter_by(email=payload['email']).one()
    assert item.topic == 'PRP у трихології'
    assert item.locale == 'uk'
    assert calls == [item]


def test_english_submission_records_locale(client, monkeypatch):
    monkeypatch.setattr('app.services.trainer_recruitment.notify', lambda a: None)
    payload = _payload()
    client.post('/en/trainers/join', data=payload)
    assert TrainerApplication.query.filter_by(email=payload['email']).one().locale == 'en'


def test_thank_you_state(client):
    html = client.get('/trainers/join?sent=1').get_data(as_text=True)
    assert 'Дякуємо' in html
    assert 'name="q_plasma_years"' not in html


@pytest.mark.parametrize('field', ['full_name', 'phone', 'email', 'specialty', 'topic',
                                   'consent', 'q_plasma_years'])
def test_required_field_missing_is_refused(client, monkeypatch, field):
    monkeypatch.setattr('app.services.trainer_recruitment.notify', lambda a: None)
    payload = _payload()
    payload.pop(field)
    resp = client.post('/trainers/join', data=payload)
    assert resp.status_code == 200
    assert TrainerApplication.query.filter_by(email=payload.get('email', '')).count() == 0


def test_choice_outside_options_is_refused(client, monkeypatch):
    monkeypatch.setattr('app.services.trainer_recruitment.notify', lambda a: None)
    payload = _payload(q_tubes_per_day='999')
    resp = client.post('/trainers/join', data=payload)
    assert resp.status_code == 200
    assert TrainerApplication.query.filter_by(email=payload['email']).count() == 0


def test_honeypot_pretends_success_and_saves_nothing(client):
    payload = _payload(website='http://spam.example')
    resp = client.post('/trainers/join', data=payload)
    assert resp.status_code == 302
    assert TrainerApplication.query.filter_by(email=payload['email']).count() == 0


def test_double_submit_keeps_both_and_does_not_fail(client, monkeypatch):
    monkeypatch.setattr('app.services.trainer_recruitment.notify', lambda a: None)
    payload = _payload()
    assert client.post('/trainers/join', data=payload).status_code == 302
    assert client.post('/trainers/join', data=payload).status_code == 302
    assert TrainerApplication.query.filter_by(email=payload['email']).count() == 2


def test_teaser_on_home_and_trainers_list(client):
    from app.models.trainer import Trainer
    # Блок тренерів на головній показується лише за наявності тренерів.
    db.session.add(Trainer(full_name='Тренер', slug=f't-{uuid4().hex[:8]}', is_active=True))
    db.session.commit()
    for url in ('/', '/trainers/'):
        html = client.get(url).get_data(as_text=True)
        assert 'iprm-recruit-cta' in html, url
        assert '/trainers/join' in html, url


def test_english_page_uses_translated_texts(client):
    html = client.get('/en/trainers/join').get_data(as_text=True)
    assert 'Your experience can be valuable to others' in html
    assert 'How long have you been using PRP and plasma therapy?' in html
    assert 'Training at IPRM is a chance to' in html
    assert 'Ваш досвід може стати цінним для інших' not in html


# --- reCAPTCHA і збій збереження --------------------------------------------

def test_failed_recaptcha_saves_nothing(client, monkeypatch):
    calls = []
    monkeypatch.setattr('app.services.trainer_recruitment.notify', calls.append)
    monkeypatch.setattr('app.trainers.routes.verify_recaptcha', lambda **kw: False)
    payload = _payload()
    resp = client.post('/trainers/join', data=payload)
    assert resp.status_code == 200
    assert TrainerApplication.query.filter_by(email=payload['email']).count() == 0
    assert calls == []


def test_commit_failure_saves_nothing_and_does_not_notify(client, monkeypatch):
    calls = []
    monkeypatch.setattr('app.services.trainer_recruitment.notify', calls.append)

    real_commit = db.session.commit

    def boom():
        # Падає лише коміт заявки: до маршруту застосунок сам комітить
        # (SiteSettings.get у before_request), і той коміт має пройти.
        if any(isinstance(obj, TrainerApplication) for obj in db.session.new):
            raise RuntimeError('db down')
        return real_commit()

    monkeypatch.setattr(db.session, 'commit', boom)
    payload = _payload()
    resp = client.post('/trainers/join', data=payload)
    monkeypatch.undo()
    assert resp.status_code == 200
    # Анкета показана знову (а не «Дякуємо»): кандидат бачить, що не пішло.
    assert 'name="q_plasma_years"' in resp.get_data(as_text=True)
    assert calls == []
    assert TrainerApplication.query.filter_by(email=payload['email']).count() == 0


def test_newline_in_full_name_is_collapsed(client, monkeypatch):
    monkeypatch.setattr('app.services.trainer_recruitment.notify', lambda a: None)
    payload = _payload(full_name='Іваненко\r\nІван  Петрович')
    assert client.post('/trainers/join', data=payload).status_code == 302
    item = TrainerApplication.query.filter_by(email=payload['email']).one()
    assert item.full_name == 'Іваненко Іван Петрович'
