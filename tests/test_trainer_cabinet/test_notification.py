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
    assert kwargs['trigger'] == 'trainer_proposal'
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


# --- A3: власний тригер і без злиття двох пропозицій у 60-секундному dedup ---

import pytest


@pytest.fixture
def smtp_stage(monkeypatch):
    """Увімкнена пошта без мережі; лічимо, скільки листів дійшло до SMTP-етапу.

    Мокаємо рівень потоку/SMTP, а не send_email: dedup, idempotency й INSERT
    у email_logs (з CHECK на тригер) мають відпрацювати по-справжньому.
    """
    from app.services import email_service
    cfg = {
        'server': 'smtp.example.com', 'port': 587, 'use_ssl': False, 'use_tls': True,
        'username': 'u@example.com', 'password': 'x', 'is_enabled': True,
        'has_password': True, 'sender': 'u@example.com',
    }
    sent = []

    class _SyncThread:
        def __init__(self, target, args=(), **_kw):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(email_service, '_get_smtp_config', lambda app: cfg)
    monkeypatch.setattr(email_service, 'Thread', _SyncThread)
    monkeypatch.setattr(EmailService, '_send_in_thread',
                        staticmethod(lambda app, msg, log_id, smtp_cfg: sent.append(log_id)))
    monkeypatch.setattr(EmailService, '_check_circuit_breaker', staticmethod(lambda: False))
    s = SiteSettings.get()
    s.trainer_contract_email = 'tc-curator-dedup@test.com'
    db.session.commit()
    return sent


def _submitted_now(trainer, title):
    from datetime import datetime, timezone
    p = TrainerCourseProposal(trainer_id=trainer.id, title=title, theses=['a'],
                              status='submitted', submitted_at=datetime.now(timezone.utc))
    db.session.add(p)
    db.session.commit()
    return p


def test_two_proposals_within_dedup_window_both_reach_smtp(smtp_stage):
    from app.models.email_log import EmailLog
    first = _submitted_now(make_trainer(make_user(), name='Перший'), 'Курс А')
    second = _submitted_now(make_trainer(make_user(), name='Другий'), 'Курс Б')
    assert EmailService.send_trainer_proposal_notification(first) is not None
    assert EmailService.send_trainer_proposal_notification(second) is not None
    assert len(smtp_stage) == 2
    logs = EmailLog.query.filter(EmailLog.id.in_(smtp_stage)).all()
    assert {log.trigger for log in logs} == {'trainer_proposal'}


def test_same_proposal_twice_sends_once(smtp_stage):
    p = _submitted_now(make_trainer(make_user()), 'Курс В')
    assert EmailService.send_trainer_proposal_notification(p) is not None
    assert EmailService.send_trainer_proposal_notification(p) is None
    assert len(smtp_stage) == 1


def test_resubmission_after_return_sends_again(smtp_stage):
    """Повторне надсилання після повернення -- нова подія (новий submitted_at)."""
    from datetime import timedelta
    p = _submitted_now(make_trainer(make_user()), 'Курс Г')
    EmailService.send_trainer_proposal_notification(p)
    p.submitted_at = p.submitted_at + timedelta(minutes=5)
    db.session.commit()
    EmailService.send_trainer_proposal_notification(p)
    assert len(smtp_stage) == 2


# --- B9: немає куди слати -- попередження в лог, а не тиша ------------------

def test_no_recipient_logs_warning(app, caplog):
    import logging
    s = SiteSettings.get()
    s.trainer_contract_email = ''
    s.email = ''
    db.session.commit()
    p = _draft(make_trainer(make_user()))
    with mock.patch.object(EmailService, 'send_email') as send, \
            caplog.at_level(logging.WARNING, logger='app.services.email_service'):
        assert EmailService.send_trainer_proposal_notification(p) is None
    send.assert_not_called()
    assert any('no recipient' in r.getMessage() for r in caplog.records
               if r.levelno == logging.WARNING)
