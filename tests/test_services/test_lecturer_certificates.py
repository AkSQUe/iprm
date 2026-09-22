"""Автовидача сертифікатів лектора на захід."""
from datetime import timedelta
from itertools import count
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.email_log import EmailLog
from app.models.lecturer_certificate import LecturerCertificate
from app.models.site_settings import SiteSettings
from app.services import certificate_service, email_service
from app.services import lecturer_certificates as lc_svc
from app.services.email_service import EmailService
from app.services.trainer_links import set_trainers
from tests.test_trainer_cabinet._factories import (
    make_course, make_instance, make_trainer,
)

# Власний лічильник номерів заходів БПР -- issue_lecturer_certificate комітить
# сам, тож рядки переживають rollback db_session і номери не мають зіткнутися
# з іншими тестами (див. test_certificate_lecturer_multi.py).
_event_numbers = count(4000000)


@pytest.fixture(autouse=True)
def bpr_settings(app):
    """Номер провайдера БПР -- без нього issue_lecturer_certificate падає ще
    до перевірки балів, яку якраз і тестуємо тут."""
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    db.session.flush()
    return settings


def _completed_instance(points=5, trainers=2):
    course = make_course()
    course.bpr_event_number = str(next(_event_numbers))
    made = [make_trainer(name=f'Тренер {i}') for i in range(trainers)]
    set_trainers(course, [t.id for t in made])
    course.bpr_lecturer_points = points
    inst = make_instance(course, days=-3, status='completed')
    db.session.commit()
    return inst, made


def test_issues_one_certificate_per_trainer(app):
    inst, made = _completed_instance(trainers=2)
    issued = lc_svc.issue_for_instance(inst)
    assert len(issued) == 2
    assert {c.trainer_id for c in issued} == {t.id for t in made}


def test_second_call_does_not_duplicate(app):
    inst, _ = _completed_instance(trainers=2)
    lc_svc.issue_for_instance(inst)
    lc_svc.issue_for_instance(inst)
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 2


def test_missing_points_issues_nothing_and_notifies_admins(app):
    inst, _ = _completed_instance(points=None, trainers=2)
    with patch(
        'app.services.email_service.EmailService'
        '.notify_lecturer_certificate_failed'
    ) as notify:
        issued = lc_svc.issue_for_instance(inst)
    assert issued == []
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 0
    assert notify.called


def test_issued_certificates_start_unsent(app):
    inst, _ = _completed_instance(trainers=1)
    issued = lc_svc.issue_for_instance(inst)
    assert issued[0].emailed_at is None


def test_missing_provider_number_issues_nothing_and_notifies_admins(app):
    inst, _ = _completed_instance(trainers=2)
    SiteSettings.get().bpr_provider_number = ''
    db.session.commit()
    with patch(
        'app.services.email_service.EmailService'
        '.notify_lecturer_certificate_failed'
    ) as notify:
        issued = lc_svc.issue_for_instance(inst)
    assert issued == []
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 0
    assert notify.called
    reason = notify.call_args.args[1]
    assert 'провайдера' in reason


def test_missing_event_number_issues_nothing_and_notifies_admins(app):
    inst, made = _completed_instance(trainers=2)
    inst.course.bpr_event_number = ''
    db.session.commit()
    with patch(
        'app.services.email_service.EmailService'
        '.notify_lecturer_certificate_failed'
    ) as notify:
        issued = lc_svc.issue_for_instance(inst)
    assert issued == []
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 0
    assert notify.called
    reason = notify.call_args.args[1]
    assert 'заходу' in reason


def test_recipient_email_falls_back_to_directory(app):
    trainer = make_trainer(name='Довідниковий Т.')
    trainer.email = 'tc-directory@test.com'
    db.session.commit()
    assert lc_svc.recipient_email(trainer) == 'tc-directory@test.com'


def test_recipient_email_prefers_account_over_directory(app):
    from tests.test_trainer_cabinet._factories import make_user

    user = make_user()
    trainer = make_trainer(user, name='Акаунтний Т.')
    trainer.email = 'tc-directory@test.com'
    db.session.commit()
    assert lc_svc.recipient_email(trainer) == user.email


def test_recipient_email_prefers_profile_over_all(app):
    from app.models.trainer_profile import TrainerProfile
    from tests.test_trainer_cabinet._factories import make_user

    user = make_user()
    trainer = make_trainer(user, name='Анкетний Т.')
    trainer.email = 'tc-directory@test.com'
    db.session.add(TrainerProfile(trainer_id=trainer.id,
                                  email='tc-profile@test.com'))
    db.session.commit()
    db.session.refresh(trainer)
    assert lc_svc.recipient_email(trainer) == 'tc-profile@test.com'


def test_recipient_email_none_when_nothing_filled(app):
    trainer = make_trainer(name='Безадресний Т.')
    db.session.commit()
    assert lc_svc.recipient_email(trainer) is None


def test_recipient_email_skips_blank_profile_email(app):
    """Анкета існує, але email у ній не заповнений (порожній рядок, не NULL)
    -- ланцюжок має провалитись до акаунта/довідника, а не зупинитись на
    порожньому значенні й повернути ''."""
    from app.models.trainer_profile import TrainerProfile

    trainer = make_trainer(name='Порожньоанкетний Т.')
    trainer.email = 'tc-directory@test.com'
    db.session.add(TrainerProfile(trainer_id=trainer.id, email=''))
    db.session.commit()
    db.session.refresh(trainer)
    assert lc_svc.recipient_email(trainer) == 'tc-directory@test.com'


# ---------------------------------------------------------------------------
# send_lecturer_certificate: ключ ідемпотентності на id сертифіката, а не на
# щось спільне для кількох подій (напр. trainer_id) -- див. брифи задачі 4.
# ---------------------------------------------------------------------------
@pytest.fixture
def enabled_mail(monkeypatch):
    """Імітувати увімкнену пошту без мережі -- як однойменна фікстура в
    test_email_service.py: мокаємо SMTP-конфіг і фонову відправку, щоб
    перевіряти сам журнал EmailLog, а не лізти в мережу чи мокати
    send_lecturer_certificate (це довело б лише факт виклику, не ключ)."""
    cfg = {
        'server': 'smtp.example.com', 'port': 587, 'use_ssl': False, 'use_tls': True,
        'username': 'u@example.com', 'password': 'x', 'is_enabled': True,
        'has_password': True, 'sender': 'u@example.com',
    }
    monkeypatch.setattr(email_service, '_get_smtp_config', lambda app: cfg)
    monkeypatch.setattr(EmailService, '_send_in_thread', staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(EmailService, '_check_circuit_breaker', staticmethod(lambda: False))


@pytest.fixture(autouse=True)
def _fake_pdf(monkeypatch):
    """PDF тут не тестуємо (WeasyPrint) -- лише те, що дійшло до журналу."""
    monkeypatch.setattr(certificate_service, 'render_lecturer_pdf', lambda lc: b'%PDF-fake%')


def _issued_certificate():
    """Один виданий сертифікат лектора на свіжому заході -- окремий курс і
    тренер на кожен виклик, щоб два виклики давали два РІЗНІ сертифікати
    (різні id -> різні idempotency_key)."""
    inst, _made = _completed_instance(trainers=1)
    return lc_svc.issue_for_instance(inst)[0]


def test_two_certificates_to_same_address_are_not_deduplicated(app, enabled_mail):
    """Якби ключ ідемпотентності був не на lecturer_cert.id, а на щось спільне
    для двох різних заходів (наприклад, trainer_id), _idempotency_seen з'їв би
    другий лист тому самому тренеру -- саме цього ключ і має не допускати."""
    cert_a = _issued_certificate()
    cert_b = _issued_certificate()

    EmailService.send_lecturer_certificate(cert_a, 'trainer-dup@test.com')
    EmailService.send_lecturer_certificate(cert_b, 'trainer-dup@test.com')

    logs = EmailLog.query.filter_by(to_email='trainer-dup@test.com').all()
    assert len(logs) == 2
    assert logs[0].idempotency_key != logs[1].idempotency_key


def test_same_certificate_twice_is_deduplicated(app, enabled_mail):
    """Зворотний бік: повторний виклик на ОДИН і той самий сертифікат (напр.
    якщо джоба пройде по ньому ще раз) не плодить другого листа."""
    cert = _issued_certificate()

    EmailService.send_lecturer_certificate(cert, 'trainer-once@test.com')
    EmailService.send_lecturer_certificate(cert, 'trainer-once@test.com')

    logs = EmailLog.query.filter_by(to_email='trainer-once@test.com').all()
    assert len(logs) == 1


# ---------------------------------------------------------------------------
# send_pending: черга розсилки (emailed_at IS NULL). Планувальник у TESTING
# вимкнено, тож тут тестується сама функція, а не обгортку scheduler_service.
# ---------------------------------------------------------------------------
def test_send_pending_marks_emailed_at(app):
    inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(inst)[0]
    cert.trainer.email = 'tc-lect@test.com'
    db.session.commit()
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate') as send:
        sent, skipped = lc_svc.send_pending()
    assert (sent, skipped) == (1, 0)
    assert send.call_count == 1
    db.session.refresh(cert)
    assert cert.emailed_at is not None


def test_send_pending_does_not_send_twice(app):
    inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(inst)[0]
    cert.trainer.email = 'tc-lect2@test.com'
    db.session.commit()
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate'):
        lc_svc.send_pending()
        sent, _ = lc_svc.send_pending()
    assert sent == 0


def test_two_certificates_for_one_trainer_give_two_letters(app):
    """60-секундне вікно дедуплікації не має зʼїдати другий сертифікат."""
    course = make_course()
    course.bpr_event_number = str(next(_event_numbers))
    trainer = make_trainer(name='Двозахідний Т.')
    trainer.email = 'tc-two@test.com'
    set_trainers(course, [trainer.id])
    course.bpr_lecturer_points = 3
    first = make_instance(course, days=-5, status='completed')
    second = make_instance(course, days=-4, status='completed')
    db.session.commit()
    lc_svc.issue_for_instance(first)
    lc_svc.issue_for_instance(second)
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate') as send:
        sent, _ = lc_svc.send_pending()
    assert sent == 2
    keys = {c.kwargs.get('to_email') or c.args[1] for c in send.call_args_list}
    assert keys == {'tc-two@test.com'}


def test_trainer_without_email_is_skipped_but_others_proceed(app):
    inst, made = _completed_instance(trainers=2)
    certs = lc_svc.issue_for_instance(inst)
    certs[0].trainer.email = 'tc-has@test.com'
    certs[1].trainer.email = None
    db.session.commit()
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate'):
        sent, skipped = lc_svc.send_pending()
    assert (sent, skipped) == (1, 1)
    db.session.refresh(certs[1])
    assert certs[1].emailed_at is None


def test_failure_on_one_record_does_not_stop_the_rest(app):
    """Збій на другому записі не має спиняти чергу -- третій має піти теж.

    Без перевірки ТРЕТЬОГО запису цей тест пройшов би і на зламаній версії,
    де `except Exception: continue` замінили на `return` (або прибрали
    внутрішній try/except): цикл спинився б на другому записі, `sent`
    все одно був би 2 менше очікуваного лише щодо цього факту -- але
    `certs[2].emailed_at` лишився б None, і саме це видає різницю між
    "пропустили один і пішли далі" та "спинились на першому ж збої".
    """
    inst, made = _completed_instance(trainers=3)
    certs = lc_svc.issue_for_instance(inst)
    for i, cert in enumerate(certs):
        cert.trainer.email = f'tc-resilience-{i}@test.com'
        # issued_at контролюємо явно: у тесті всі три сертифікати можуть
        # видатись у ту саму мілісекунду, а send_pending сортує саме за
        # issued_at -- без розбіжних значень порядок черги був би
        # недетермінованим і side_effect міг би впасти не на тому записі.
        cert.issued_at = certs[0].issued_at + timedelta(seconds=i)
    db.session.commit()

    with patch(
        'app.services.email_service.EmailService.send_lecturer_certificate',
        side_effect=[None, RuntimeError('smtp down'), None],
    ):
        sent, _ = lc_svc.send_pending()

    assert sent == 2
    db.session.refresh(certs[0])
    db.session.refresh(certs[1])
    db.session.refresh(certs[2])
    assert certs[0].emailed_at is not None
    assert certs[1].emailed_at is None
    assert certs[2].emailed_at is not None
