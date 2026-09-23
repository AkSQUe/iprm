"""Наскрізні сценарії сертифікатів лектора -- стики між задачами.

Кожна задача функції пройшла свої тести, а дефекти фінальної рецензії жили
саме між ними: видача -> розсилка -> перевидача -> знову розсилка; перехід
статусу маршрутом -> фонова розсилка; кабінет тренера -> медіа-реєстр. Тут
ці ланцюжки проходять цілком, зі справжнім send_email (підмінено лише
транспорт, див. `enabled_mail`) і без мока send_lecturer_certificate.
"""
import json
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.email_log import EmailLog
from app.models.lecturer_certificate import LecturerCertificate
from app.models.media_file import MediaFile
from app.models.mixins import utcnow
from app.models.trainer import Trainer
from app.services import certificate_service
from app.services import lecturer_certificates as lc_svc
from app.services.trainer_links import set_trainers
from tests.support.rbac import make_super_admin, switch_user
from tests.test_services.test_lecturer_certificates import (  # noqa: F401
    _completed_instance, _event_numbers, bpr_settings, enabled_mail,
)
from tests.test_trainer_cabinet._factories import (
    login, make_course, make_instance, make_trainer, make_user,
)
from tests.test_trainer_cabinet.test_routes_certificates import (  # noqa: F401
    _InputValueFinder, _png, media_root,
)


@pytest.fixture
def fake_pdf(monkeypatch):
    """Там, де PDF не предмет перевірки, WeasyPrint лише гальмує прогін."""
    monkeypatch.setattr(certificate_service, 'render_lecturer_pdf',
                        lambda lc: b'%PDF-fake%')


def _certificate_with_address(email):
    inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(inst)[0]
    cert.trainer.email = email
    db.session.commit()
    return inst, cert


def _admin(client):
    admin = make_super_admin(email='tc-e2e-admin@test.com')
    db.session.commit()
    switch_user(client, admin)
    return admin


def _instance_for_transition(status='active'):
    course = make_course()
    course.bpr_event_number = str(next(_event_numbers))
    trainer = make_trainer(name='Наскрізний Л.')
    trainer.email = 'tc-e2e-lecturer@test.com'
    set_trainers(course, [trainer.id])
    course.bpr_lecturer_points = 4
    inst = make_instance(course, days=-2, status=status)
    db.session.commit()
    return inst, trainer


# 1. C1 -------------------------------------------------------------------
def test_reissued_certificate_is_emailed_again(app, enabled_mail, fake_pdf):
    """Перевидача зберігає id і скидає emailed_at. З ключем листа лише на id
    send_email мовчки пропускав виправлену версію як дубль, а send_pending
    все одно ставив emailed_at -- тренер лишався зі старим PDF."""
    inst, cert = _certificate_with_address('tc-e2e-reissue@test.com')
    # Перевидача в ту саму секунду зіллялася б із першим листом (свідомо
    # прийнятий компроміс ключа) -- у житті між ними хвилини й дні.
    cert.issued_at = cert.issued_at - timedelta(minutes=5)
    db.session.commit()
    assert lc_svc.send_pending() == (1, 0)

    certificate_service.reissue_lecturer_certificate(inst, cert.trainer)
    db.session.refresh(cert)
    assert cert.emailed_at is None

    assert lc_svc.send_pending() == (1, 0)
    logs = EmailLog.query.filter_by(to_email='tc-e2e-reissue@test.com').all()
    assert len(logs) == 2
    assert len({log.idempotency_key for log in logs}) == 2
    assert len(enabled_mail.outbox) == 2


# 2. I1 -------------------------------------------------------------------
@pytest.mark.parametrize('state', ['disabled', 'breaker', 'suppressed'])
def test_undelivered_letter_keeps_certificate_in_queue(
        app, enabled_mail, fake_pdf, state):
    from app.models.email_suppression import EmailSuppression

    _inst, cert = _certificate_with_address(f'tc-e2e-{state}@test.com')
    if state == 'disabled':
        enabled_mail.cfg['is_enabled'] = False
    elif state == 'breaker':
        enabled_mail.breaker_open = True
    else:
        EmailSuppression.add(f'tc-e2e-{state}@test.com')
        db.session.commit()

    sent, _ = lc_svc.send_pending()

    assert sent == 0
    db.session.refresh(cert)
    assert cert.emailed_at is None
    assert enabled_mail.outbox == []


# 3. Маршрут статусу -> фонова розсилка -----------------------------------
def test_status_route_to_letter_with_pdf(client, enabled_mail):
    """Справжній рендер PDF і справжній send_lecturer_certificate: у вихідному
    листі -- PDF-вкладення з номером сертифіката."""
    _admin(client)
    inst, trainer = _instance_for_transition()

    resp = client.post(f'/admin/instances/{inst.id}/status',
                       data={'status': 'completed'})
    assert resp.status_code in (200, 302)

    assert lc_svc.send_pending() == (1, 0)
    cert = LecturerCertificate.query.filter_by(
        instance_id=inst.id, trainer_id=trainer.id).one()
    assert cert.emailed_at is not None
    log = EmailLog.query.filter_by(to_email='tc-e2e-lecturer@test.com').one()
    assert log.status == 'pending'
    assert log.trigger == 'certificate'

    msg = enabled_mail.outbox[0]
    assert msg.recipients == ['tc-e2e-lecturer@test.com']
    pdfs = [a for a in msg.attachments if a.content_type == 'application/pdf']
    assert len(pdfs) == 1
    assert pdfs[0].filename == f'lecturer-{cert.number}.pdf'
    assert pdfs[0].data[:4] == b'%PDF'


# 4. I3 -------------------------------------------------------------------
def test_edit_form_transition_issues_certificate(client):
    _admin(client)
    inst, trainer = _instance_for_transition()

    resp = client.post(f'/admin/instances/{inst.id}/edit', data={
        'course_id': str(inst.course_id),
        'start_date': '2026-09-20T10:00',
        'event_format': 'offline',
        'status': 'completed',
    })
    assert resp.status_code == 302

    db.session.refresh(inst)
    assert inst.status == 'completed'
    assert LecturerCertificate.query.filter_by(
        instance_id=inst.id, trainer_id=trainer.id).count() == 1


def test_edit_form_without_transition_issues_nothing(client):
    """Зворотний бік: збереження форми вже завершеного заходу -- не перехід."""
    _admin(client)
    inst, trainer = _instance_for_transition(status='completed')

    client.post(f'/admin/instances/{inst.id}/edit', data={
        'course_id': str(inst.course_id),
        'start_date': '2026-09-20T10:00',
        'event_format': 'offline',
        'status': 'completed',
    })

    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 0


# 5. C3 -------------------------------------------------------------------
def test_daily_maintenance_skips_historical_instance(app, enabled_mail, fake_pdf):
    """Захід з імпорту, що завершився 60 днів тому: усі передумови є, тренер
    без сертифіката -- і все одно ні видачі, ні листа, ні рядка у звіті."""
    from unittest.mock import patch

    inst, (trainer,) = _completed_instance(trainers=1)
    trainer.email = 'tc-e2e-history@test.com'
    inst.start_date = utcnow() - timedelta(days=60)
    db.session.commit()

    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_report') as report:
        stats = lc_svc.daily_maintenance()
    lc_svc.send_pending()

    assert stats['issued'] == 0
    assert stats['blocked'] == 0
    assert not report.called
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 0
    assert EmailLog.query.filter_by(to_email='tc-e2e-history@test.com').count() == 0


# 6. C2 -------------------------------------------------------------------
def test_cabinet_cannot_take_foreign_media(client, media_root):
    import os

    victim_user = make_user()
    victim = make_trainer(victim_user, name='Жертва А.')
    login(client, victim_user)
    uploaded = client.post('/trainer/certificates/upload',
                           data={'file': (_png(), 'v.png')},
                           content_type='multipart/form-data').get_json()
    # Ще не збережене медіа -- entity_type IS NULL: саме таке найлегше
    # перехопити, бо «власника» поки не видно ні з якої сутності.
    media = db.session.get(MediaFile, uploaded['media_id'])
    before = (media.entity_type, media.entity_id, media.file_path,
              media.uploaded_by)

    attacker_user = make_user()
    attacker = make_trainer(attacker_user, name='Нападник Б.')
    login(client, attacker_user)
    client.post('/trainer/certificates', data={'certificates': json.dumps([{
        'url': uploaded['url'], 'thumb': uploaded['thumb'],
        'media_id': uploaded['media_id'], 'caption': 'Моє',
    }])})

    db.session.expire_all()
    media = db.session.get(MediaFile, uploaded['media_id'])
    assert (media.entity_type, media.entity_id, media.file_path,
            media.uploaded_by) == before
    assert os.path.exists(media.abs_path)
    assert not (db.session.get(Trainer, attacker.id).certificates or [])
    assert media.entity_id != attacker.id


def lc_svc_limit():
    """Типовий ліміт send_pending -- з сигнатури, а не переписаним числом."""
    import inspect
    return inspect.signature(lc_svc.send_pending).parameters['limit'].default


# 7. I2 -------------------------------------------------------------------
def test_addressless_backlog_does_not_starve_sendable(app, enabled_mail, fake_pdf):
    early = utcnow() - timedelta(days=3)
    inst = make_instance(make_course(), days=-3, status='completed')
    for i in range(lc_svc_limit() + 5):
        trainer = make_trainer(name=f'Без адреси {i}')
        db.session.add(LecturerCertificate(
            instance_id=inst.id, trainer_id=trainer.id,
            number=f'E2E-NA-{i}', recipient_name='Т', event_title='Захід',
            issued_at=early + timedelta(seconds=i),
        ))
    db.session.commit()
    _inst, cert = _certificate_with_address('tc-e2e-late@test.com')

    sent, _ = lc_svc.send_pending()

    assert sent == 1
    db.session.refresh(cert)
    assert cert.emailed_at is not None
    assert [m.recipients for m in enabled_mail.outbox] == [['tc-e2e-late@test.com']]


# 8. Зберегти без змін нічого не стирає -----------------------------------
def test_saving_unchanged_form_keeps_certificates(client, media_root):
    user = make_user()
    trainer = make_trainer(user, name='Незмінний Т.')
    login(client, user)
    uploaded = client.post('/trainer/certificates/upload',
                           data={'file': (_png(), 'k.png')},
                           content_type='multipart/form-data').get_json()
    client.post('/trainer/certificates', data={'certificates': json.dumps([
        {'url': uploaded['url'], 'thumb': uploaded['thumb'],
         'media_id': uploaded['media_id'], 'caption': 'Диплом "Ін\'єкції"'},
    ])})
    db.session.refresh(trainer)
    saved = list(trainer.certificates)
    assert len(saved) == 1

    page = client.get('/trainer/certificates')
    parser = _InputValueFinder('regalia-cert-field')
    parser.feed(page.data.decode('utf-8'))
    assert parser.value is not None

    client.post('/trainer/certificates', data={'certificates': parser.value})

    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).certificates == saved
