"""E1: лист тренеру, коли куратор прийняв або повернув пропозицію курсу.

Без цього листа тренер дізнавався про рішення, лише зайшовши в кабінет
навмання; повернута на доопрацювання пропозиція могла лежати тижнями.
"""
import logging
from unittest import mock

from flask_babel import force_locale

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.services.email_service import EmailService
from tests.support.rbac import make_super_admin
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _admin(client):
    admin = make_super_admin(email='tc-status-admin@test.com')
    db.session.commit()
    login(client, admin)
    return admin


def _submitted(trainer, title='КОС'):
    p = TrainerCourseProposal(trainer_id=trainer.id, title=title, theses=['a'],
                              status='submitted')
    db.session.add(p)
    db.session.commit()
    return p


def _site(base='https://iprm.test'):
    s = SiteSettings.get()
    s.website_url = base
    db.session.commit()
    return s


def test_accept_notifies_trainer_account_email(client):
    _site()
    user = make_user()
    trainer = make_trainer(user)
    p = _submitted(trainer)
    _admin(client)
    with mock.patch.object(EmailService, 'send_email') as send:
        client.post(f'/admin/trainers/proposals/{p.id}/accept')
    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert kwargs['to'] == user.email
    assert kwargs['template_name'] == 'trainer_proposal_status'
    assert kwargs['trigger'] == 'trainer_proposal'
    assert kwargs['idempotency_key'].startswith(f'trainer-proposal-status-{p.id}-accepted-')
    assert kwargs['context']['proposal_url'] == f'https://iprm.test/trainer/proposals/{p.id}'
    # Отримувач у context['user'] -- саме за ним _recipient_locale обирає мову.
    assert kwargs['context']['user'].id == user.id
    assert callable(kwargs['subject'])


def test_return_notifies_trainer_with_comment(client):
    _site()
    user = make_user()
    p = _submitted(make_trainer(user))
    _admin(client)
    with mock.patch.object(EmailService, 'send_email') as send:
        client.post(f'/admin/trainers/proposals/{p.id}/return',
                    data={f'p{p.id}-comment': 'Уточніть тези'})
    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert kwargs['to'] == user.email
    assert kwargs['idempotency_key'].startswith(f'trainer-proposal-status-{p.id}-draft-')
    assert kwargs['context']['proposal'].curator_comment == 'Уточніть тези'


def test_unaccept_sends_nothing(client):
    user = make_user()
    p = _submitted(make_trainer(user))
    p.status = 'accepted'
    db.session.commit()
    _admin(client)
    with mock.patch.object(EmailService, 'send_email') as send:
        client.post(f'/admin/trainers/proposals/{p.id}/unaccept')
    db.session.expire_all()
    assert p.status == 'submitted'
    send.assert_not_called()


def test_failed_transition_sends_nothing(client):
    p = _submitted(make_trainer(make_user()))
    p.status = 'draft'
    db.session.commit()
    _admin(client)
    with mock.patch.object(EmailService, 'send_email') as send:
        client.post(f'/admin/trainers/proposals/{p.id}/accept')
    send.assert_not_called()


def test_mail_failure_does_not_break_accept(client, caplog):
    p = _submitted(make_trainer(make_user()))
    _admin(client)
    with mock.patch.object(EmailService, 'send_email', side_effect=RuntimeError('smtp down')), \
            caplog.at_level(logging.ERROR):
        resp = client.post(f'/admin/trainers/proposals/{p.id}/accept')
    assert resp.status_code == 302
    db.session.expire_all()
    assert p.status == 'accepted'
    assert any('proposal' in r.getMessage() and r.exc_info for r in caplog.records)


def test_fallback_to_trainer_public_email_without_account(app):
    trainer = make_trainer()
    trainer.email = 'tc-public@test.com'
    db.session.commit()
    p = _submitted(trainer)
    with mock.patch.object(EmailService, 'send_email') as send:
        EmailService.send_trainer_proposal_status(p)
    assert send.call_args.kwargs['to'] == 'tc-public@test.com'
    assert send.call_args.kwargs['context']['user'] is None


def test_no_recipient_logs_warning(app, caplog):
    p = _submitted(make_trainer())
    with mock.patch.object(EmailService, 'send_email') as send, \
            caplog.at_level(logging.WARNING, logger='app.services.email_service'):
        assert EmailService.send_trainer_proposal_status(p) is None
    send.assert_not_called()
    assert any('no recipient' in r.getMessage() for r in caplog.records)


def test_subject_is_translated_and_has_no_newline(app):
    user = make_user()
    p = _submitted(make_trainer(user), title='Курс\r\nBcc: x@evil.com')
    p.status = 'accepted'
    db.session.commit()
    with mock.patch.object(EmailService, 'send_email') as send:
        EmailService.send_trainer_proposal_status(p)
    subject = send.call_args.kwargs['subject']
    with force_locale('uk'):
        uk = subject()
    with force_locale('en'):
        en = subject()
    assert uk.startswith('Пропозицію курсу прийнято')
    assert en.startswith('Your course proposal has been accepted')
    assert '\r' not in uk and '\n' not in uk


def test_same_decision_gives_same_key(app):
    """Повторний виклик для того самого рішення (той самий updated_at) дає той
    самий ключ -- і send_email відсіює дубль через _idempotency_seen."""
    p = _submitted(make_trainer(make_user()))
    with mock.patch.object(EmailService, 'send_email') as send:
        EmailService.send_trainer_proposal_status(p)
        EmailService.send_trainer_proposal_status(p)
    keys = [c.kwargs['idempotency_key'] for c in send.call_args_list]
    assert keys[0] == keys[1]


def test_template_renders_comment_and_link(app):
    from flask import render_template
    user = make_user()
    trainer = make_trainer(user, name='Петренко П.')
    p = _submitted(trainer)
    p.status = 'draft'
    p.curator_comment = 'Додайте тези про протоколи'
    db.session.commit()
    html = render_template('emails/trainer_proposal_status.html', proposal=p,
                           trainer=trainer, user=user,
                           proposal_url='https://iprm.test/trainer/proposals/1',
                           site_settings=SiteSettings.get())
    assert 'Додайте тези про протоколи' in html
    assert 'https://iprm.test/trainer/proposals/1' in html
    assert 'КОС' in html
    assert 'доопрацювання' in html


def test_template_renders_accepted(app):
    from flask import render_template
    trainer = make_trainer(make_user())
    p = _submitted(trainer)
    p.status = 'accepted'
    db.session.commit()
    html = render_template('emails/trainer_proposal_status.html', proposal=p,
                           trainer=trainer, user=None,
                           proposal_url='https://iprm.test/trainer/proposals/1',
                           site_settings=SiteSettings.get())
    assert 'прийнято' in html
