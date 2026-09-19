from unittest import mock

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.services.email_service import EmailService
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _draft(trainer):
    p = TrainerCourseProposal(trainer_id=trainer.id, title='КОС', theses=['a'])
    db.session.add(p)
    db.session.commit()
    return p


def test_submit_sends_to_contract_email(client):
    s = SiteSettings.get()
    s.trainer_contract_email = 'curator@test.com'
    db.session.commit()
    user = make_user()
    trainer = make_trainer(user, name='Петренко П.')
    p = _draft(trainer)
    login(client, user)
    with mock.patch.object(EmailService, 'send_email') as send:
        client.post(f'/trainer/proposals/{p.id}/submit')
    send.assert_called_once()
    args, kwargs = send.call_args
    to = kwargs.get('to', args[0] if args else None)
    assert to == 'curator@test.com'
    assert kwargs['template_name'] == 'trainer_proposal_submitted'
    assert kwargs['trigger'] == 'course_request'
    assert 'КОС' in kwargs['subject']


def test_fallback_to_site_email(client):
    s = SiteSettings.get()
    s.trainer_contract_email = ''
    s.email = 'office@test.com'
    db.session.commit()
    user = make_user()
    p = _draft(make_trainer(user))
    login(client, user)
    with mock.patch.object(EmailService, 'send_email') as send:
        client.post(f'/trainer/proposals/{p.id}/submit')
    args, kwargs = send.call_args
    assert kwargs.get('to', args[0] if args else None) == 'office@test.com'


def test_template_renders(app):
    user = make_user()
    trainer = make_trainer(user, name='Петренко П.')
    p = _draft(trainer)
    from flask import render_template
    html = render_template('emails/trainer_proposal_submitted.html', proposal=p,
                           trainer=trainer, admin_url='https://x/admin',
                           site_settings=SiteSettings.get())
    assert 'Петренко П.' in html and 'КОС' in html
