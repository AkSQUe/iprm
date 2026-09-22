from app.extensions import db
from app.models.trainer_profile import TrainerProfile
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _data(**over):
    data = {
        'full_name': 'Іваненко Іван Іванович', 'birth_date': '1985-03-02',
        'education': 'НМУ ім. Богомольця', 'position_titles': 'Лікар-лаборант, к.мед.н.',
        'workplace': 'Клініка, Київ', 'phone': '+380671234567', 'email': 'ivan@test.com',
        'social_links': 'https://facebook.com/ivan', 'photo_url': '',
        'fop_recipient': 'ФОП Іваненко І.І.', 'fop_iban': 'UA213052990000026003006239637',
        'fop_rnokpp': '1234567890', 'fop_payment_purpose': 'Послуги за КВЕД 85.59',
        'card_number': '4149 6090 1234 5678', 'tax_id': '1234567890',
        'registration_address': 'м. Київ, вул. Хрещатик, 1', 'edrpou': '',
    }
    data.update(over)
    return data


def test_profile_save_and_prefill(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    resp = client.post('/trainer/profile', data=_data(), follow_redirects=True)
    assert resp.status_code == 200
    profile = TrainerProfile.query.filter_by(trainer_id=trainer.id).one()
    assert profile.fop_iban == 'UA213052990000026003006239637'
    assert profile.is_complete
    html = client.get('/trainer/profile').get_data(as_text=True)
    assert 'UA213052990000026003006239637' in html
    assert 'Іваненко Іван Іванович' in html


def test_profile_invalid_email_rerenders(client):
    user = make_user()
    make_trainer(user)
    login(client, user)
    resp = client.post('/trainer/profile', data=_data(email='not-an-email'))
    assert resp.status_code == 200
    assert 'form-error' in resp.get_data(as_text=True)
    assert TrainerProfile.query.count() == 0 or not TrainerProfile.query.first().email


def test_clearing_secret_keeps_nothing(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    client.post('/trainer/profile', data=_data())
    client.post('/trainer/profile', data=_data(card_number=''))
    db.session.expire_all()
    assert TrainerProfile.query.filter_by(trainer_id=trainer.id).one().card_number == ''


# --- B4: зміна реквізитів не проходить мовчки --------------------------------

import logging  # noqa: E402
from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from app.models.site_settings import SiteSettings  # noqa: E402
from app.services.email_service import EmailService  # noqa: E402

_NEW_IBAN = 'UA903052992990004149123456789'


@pytest.fixture
def curator_email():
    s = SiteSettings.get()
    s.trainer_contract_email = 'tc-curator@test.com'
    db.session.commit()
    return s.trainer_contract_email


def _audit(caplog):
    return [r.getMessage() for r in caplog.records if r.name == 'audit']


def test_first_fill_is_audited_without_email(client, caplog, curator_email):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    with mock.patch.object(EmailService, 'send_email') as send, \
            caplog.at_level(logging.INFO, logger='audit'):
        client.post('/trainer/profile', data=_data())
    send.assert_not_called()
    msgs = [m for m in _audit(caplog) if 'changed requisites' in m]
    assert msgs == [f'Trainer {trainer.id} changed requisites: '
                    'fop_iban, fop_rnokpp, card_number, tax_id']


def test_requisites_change_audited_and_curator_notified(client, caplog, curator_email):
    user = make_user()
    trainer = make_trainer(user, name='Петренко П.')
    login(client, user)
    client.post('/trainer/profile', data=_data())
    with mock.patch.object(EmailService, 'send_email') as send, \
            caplog.at_level(logging.INFO, logger='audit'):
        resp = client.post('/trainer/profile', data=_data(fop_iban=_NEW_IBAN))
    assert resp.status_code == 302
    msgs = [m for m in _audit(caplog) if 'changed requisites' in m]
    assert msgs == [f'Trainer {trainer.id} changed requisites: fop_iban']
    # Лише назви полів: жодне значення не потрапляє в журнал.
    assert _NEW_IBAN not in ' '.join(_audit(caplog))
    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert kwargs['to'] == curator_email
    assert kwargs['trigger'] == 'trainer_requisites'
    assert kwargs['template_name'] == 'trainer_requisites_changed'
    assert 'Петренко П.' in kwargs['subject']


def test_unchanged_requisites_neither_audited_nor_emailed(client, caplog, curator_email):
    user = make_user()
    make_trainer(user)
    login(client, user)
    client.post('/trainer/profile', data=_data())
    with mock.patch.object(EmailService, 'send_email') as send, \
            caplog.at_level(logging.INFO, logger='audit'):
        client.post('/trainer/profile', data=_data(phone='+380501112233'))
    send.assert_not_called()
    assert not [m for m in _audit(caplog) if 'changed requisites' in m]


def test_mail_failure_does_not_break_saving(client, curator_email):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    client.post('/trainer/profile', data=_data())
    with mock.patch.object(EmailService, 'send_email', side_effect=RuntimeError('smtp')):
        resp = client.post('/trainer/profile', data=_data(tax_id='9876543210'))
    assert resp.status_code == 302
    db.session.expire_all()
    assert TrainerProfile.query.filter_by(trainer_id=trainer.id).one().tax_id == '9876543210'


def test_requisites_email_renders_without_values(app):
    from flask import render_template
    trainer = make_trainer(make_user(), name='Петренко П.')
    html = render_template(
        'emails/trainer_requisites_changed.html', trainer=trainer,
        fields=['IBAN', 'Номер картки'], admin_url='https://x/admin',
        site_settings=SiteSettings.get())
    assert 'Петренко П.' in html and 'IBAN' in html and 'Номер картки' in html


def test_requisites_email_goes_through_check(app, monkeypatch):
    """Справжній INSERT у email_logs: тригер має бути дозволений CHECK-ом."""
    from app.models.email_log import EmailLog
    from app.services import email_service
    monkeypatch.setattr(email_service, '_get_smtp_config', lambda a: {
        'server': 's', 'port': 587, 'use_ssl': False, 'use_tls': True,
        'username': 'u@example.com', 'password': 'x', 'is_enabled': True,
        'has_password': True, 'sender': 'u@example.com'})
    monkeypatch.setattr(EmailService, '_send_in_thread',
                        staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(EmailService, '_check_circuit_breaker', staticmethod(lambda: False))

    class _NoThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(email_service, 'Thread', _NoThread)
    s = SiteSettings.get()
    s.trainer_contract_email = 'tc-curator-req@test.com'
    db.session.commit()
    trainer = make_trainer(make_user())
    profile = TrainerProfile(trainer_id=trainer.id)
    db.session.add(profile)
    db.session.commit()
    log = EmailService.send_trainer_requisites_notification(trainer, ['fop_iban'])
    assert log is not None
    assert db.session.get(EmailLog, log.id).trigger == 'trainer_requisites'


# --- B6: з файлу фото на посилання ---------------------------------------------

def _with_media_photo(trainer):
    from app.models.media_file import MediaFile
    media = MediaFile(filename='tc-photo.webp', file_path='2026/09/tc-photo.webp',
                      mime_type='image/webp')
    db.session.add(media)
    db.session.flush()
    profile = TrainerProfile(trainer_id=trainer.id, photo_media_id=media.id)
    db.session.add(profile)
    db.session.commit()
    return profile


def test_remove_photo_clears_uploaded_file(client):
    user = make_user()
    trainer = make_trainer(user)
    _with_media_photo(trainer)
    login(client, user)
    client.post('/trainer/profile', data=_data(
        remove_photo='y', photo_url='https://drive.google.com/photo.jpg'))
    db.session.expire_all()
    profile = TrainerProfile.query.filter_by(trainer_id=trainer.id).one()
    assert profile.photo_media_id is None
    assert profile.photo_src == 'https://drive.google.com/photo.jpg'


def test_photo_kept_without_explicit_checkbox(client):
    user = make_user()
    trainer = make_trainer(user)
    media_id = _with_media_photo(trainer).photo_media_id
    login(client, user)
    client.post('/trainer/profile', data=_data(photo_url='https://drive.google.com/photo.jpg'))
    db.session.expire_all()
    assert TrainerProfile.query.filter_by(trainer_id=trainer.id).one().photo_media_id == media_id


def test_remove_checkbox_shown_only_with_uploaded_photo(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    assert 'name="remove_photo"' not in client.get('/trainer/profile').get_data(as_text=True)
    _with_media_photo(trainer)
    html = client.get('/trainer/profile').get_data(as_text=True)
    assert 'name="remove_photo"' in html
    assert 'Зараз використовується завантажений файл' in html


def test_professional_certificates_is_saved(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    text = 'Сертифікат A, 2024\nСертифікат B, 2025'
    resp = client.post('/trainer/profile', data=_data(professional_certificates=text), follow_redirects=True)
    assert resp.status_code == 200
    db.session.refresh(trainer)
    assert trainer.profile.professional_certificates == text


def test_empty_professional_certificates_does_not_break_completeness(app):
    """Анкета без нового поля лишається повною.

    Перевіряємо саме поведінку `is_complete`, а не членство в кортежі
    REQUIRED_FOR_COMPLETE: тест про кортеж стверджував би про оголошення й
    мовчки пройшов би, якби повнота рахувалась деінде.
    """
    from app.models.trainer_profile import TrainerProfile

    trainer = make_trainer(name='Повний Т.')
    profile = TrainerProfile(
        trainer_id=trainer.id, full_name='Повний Т.', phone='+380671234567',
        email='tc-complete@test.com', fop_iban='UA000000000000000000000000000',
        fop_rnokpp='1234567890', tax_id='1234567890',
        registration_address='м. Київ',
        professional_certificates=None,
    )
    db.session.add(profile)
    db.session.commit()
    assert profile.is_complete is True
