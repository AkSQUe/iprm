"""Автовидача сертифікатів лектора на захід."""
from datetime import timedelta
from itertools import count
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.email_log import EmailLog
from app.models.lecturer_certificate import LecturerCertificate
from app.models.mixins import utcnow
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
# send_lecturer_certificate: ключ ідемпотентності на версію сертифіката (id +
# issued_at), а не на щось спільне для кількох подій (напр. trainer_id) --
# див. брифи задачі 4 і фінальну рецензію (C1).
# ---------------------------------------------------------------------------
class _MailSwitch:
    """Керування ізольованою поштою з тесту: `cfg['is_enabled']` -- вимкнути
    пошту в налаштуваннях, `breaker_open` -- відкрити circuit breaker,
    `outbox` -- повідомлення, які пішли б у SMTP (з вкладеннями)."""

    def __init__(self):
        self.cfg = {
            'server': 'smtp.example.com', 'port': 587, 'use_ssl': False,
            'use_tls': True, 'username': 'u@example.com', 'password': 'x',
            'is_enabled': True, 'has_password': True, 'sender': 'u@example.com',
        }
        self.breaker_open = False
        self.outbox = []


@pytest.fixture
def enabled_mail(monkeypatch):
    """Імітувати увімкнену пошту без мережі -- як однойменна фікстура в
    test_email_service.py: мокаємо SMTP-конфіг і фонову відправку, щоб
    перевіряти сам журнал EmailLog, а не лізти в мережу чи мокати
    send_lecturer_certificate (це довело б лише факт виклику, не ключ).

    Справжній send_email з усіма його гардами лишається; підмінено лише
    транспорт і два входи гардів, якими тест перемикає стан пошти."""
    switch = _MailSwitch()
    monkeypatch.setattr(email_service, '_get_smtp_config', lambda app: switch.cfg)
    monkeypatch.setattr(
        EmailService, '_send_in_thread',
        staticmethod(lambda app, msg, log_id, cfg: switch.outbox.append(msg)))
    monkeypatch.setattr(EmailService, '_check_circuit_breaker',
                        staticmethod(lambda: switch.breaker_open))
    return switch


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
def _queued(status='pending'):
    """Те, що повертає send_email, коли лист поставлено в чергу: EmailLog зі
    статусом. MagicMock тут не годиться -- send_pending читає саме статус."""
    return SimpleNamespace(status=status)


def test_send_pending_marks_emailed_at(app, enabled_mail):
    inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(inst)[0]
    cert.trainer.email = 'tc-lect@test.com'
    db.session.commit()
    sent, skipped = lc_svc.send_pending()
    assert (sent, skipped) == (1, 0)
    assert len(enabled_mail.outbox) == 1
    db.session.refresh(cert)
    assert cert.emailed_at is not None


def test_send_pending_does_not_send_twice(app, enabled_mail):
    inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(inst)[0]
    cert.trainer.email = 'tc-lect2@test.com'
    db.session.commit()
    lc_svc.send_pending()
    sent, _ = lc_svc.send_pending()
    assert sent == 0
    assert len(enabled_mail.outbox) == 1


def test_two_certificates_for_one_trainer_give_two_letters(app, enabled_mail):
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
    sent, _ = lc_svc.send_pending()
    assert sent == 2
    assert {m.recipients[0] for m in enabled_mail.outbox} == {'tc-two@test.com'}
    assert len(enabled_mail.outbox) == 2


def test_trainer_without_email_is_skipped_but_others_proceed(app, enabled_mail):
    inst, made = _completed_instance(trainers=2)
    certs = lc_svc.issue_for_instance(inst)
    certs[0].trainer.email = 'tc-has@test.com'
    certs[1].trainer.email = None
    db.session.commit()
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
        side_effect=[_queued(), RuntimeError('smtp down'), _queued()],
    ):
        sent, _ = lc_svc.send_pending()

    assert sent == 2
    db.session.refresh(certs[0])
    db.session.refresh(certs[1])
    db.session.refresh(certs[2])
    assert certs[0].emailed_at is not None
    assert certs[1].emailed_at is None
    assert certs[2].emailed_at is not None


# ---------------------------------------------------------------------------
# send_pending: emailed_at -- лише коли лист справді поставлено в чергу або
# надіслано (фінальна рецензія, I1). Усе, що send_email відхилив мовчки,
# лишається в черзі й видиме у щоденному звіті.
# ---------------------------------------------------------------------------
def _pending_with_address(email):
    inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(inst)[0]
    cert.trainer.email = email
    db.session.commit()
    return cert


def test_send_pending_leaves_queue_when_mail_disabled(app, enabled_mail):
    cert = _pending_with_address('tc-disabled@test.com')
    enabled_mail.cfg['is_enabled'] = False
    sent, _ = lc_svc.send_pending()
    assert sent == 0
    db.session.refresh(cert)
    assert cert.emailed_at is None
    assert enabled_mail.outbox == []


def test_send_pending_leaves_queue_when_circuit_breaker_open(app, enabled_mail):
    cert = _pending_with_address('tc-breaker@test.com')
    enabled_mail.breaker_open = True
    sent, _ = lc_svc.send_pending()
    assert sent == 0
    db.session.refresh(cert)
    assert cert.emailed_at is None


def test_send_pending_leaves_queue_when_address_suppressed(app, enabled_mail):
    from app.models.email_suppression import EmailSuppression

    cert = _pending_with_address('tc-suppressed@test.com')
    EmailSuppression.add('tc-suppressed@test.com')
    db.session.commit()
    sent, skipped = lc_svc.send_pending()
    assert (sent, skipped) == (0, 1)
    db.session.refresh(cert)
    assert cert.emailed_at is None
    assert enabled_mail.outbox == []


def test_send_pending_stops_tick_on_global_mail_failure(app, enabled_mail):
    """Вимкнена пошта й відкритий breaker -- стан пошти загалом, а не
    конкретного листа: кожна наступна спроба в тому ж тіку дала б ще один
    'failed' у журналі (і ще один рендер PDF). З breaker-ом це
    самопідживлення: 'failed' від черги тримали б його відкритим, і пошта
    сайту не відновилась би ніколи. Тому -- одна спроба на тік."""
    _pending_with_address('tc-stop-a@test.com')
    _pending_with_address('tc-stop-b@test.com')
    enabled_mail.cfg['is_enabled'] = False
    lc_svc.send_pending()
    failed = EmailLog.query.filter(
        EmailLog.to_email.in_(['tc-stop-a@test.com', 'tc-stop-b@test.com']),
        EmailLog.status == 'failed',
    ).count()
    assert failed == 1


def test_send_pending_counts_already_sent_version_as_emailed(app, enabled_mail):
    """None від send_email через idempotent skip ТІЄЇ Ж версії -- лист уже
    пішов (наприклад, попередній тік упав між відправкою й комітом
    emailed_at). Вважати його ненадісланим означало б вічно тримати запис у
    черзі та щодня показувати адміну як застряглий."""
    cert = _pending_with_address('tc-seen@test.com')
    EmailService.send_lecturer_certificate(cert, 'tc-seen@test.com')
    assert cert.emailed_at is None
    sent, _ = lc_svc.send_pending()
    assert sent == 1
    db.session.refresh(cert)
    assert cert.emailed_at is not None
    assert EmailLog.query.filter_by(to_email='tc-seen@test.com').count() == 1


# ---------------------------------------------------------------------------
# send_pending: черга не застрягає (фінальна рецензія, I2).
# ---------------------------------------------------------------------------
def test_addressless_head_of_queue_does_not_block_sendable(app, enabled_mail):
    """55 безадресних з раннім issued_at не мають займати ліміт 50: інакше
    той, кому є куди слати, не отримав би листа ніколи."""
    early = utcnow() - timedelta(days=2)
    inst = make_instance(make_course(), days=-3, status='completed')
    trainers = [make_trainer(name=f'Безадресний {i}') for i in range(55)]
    for i, trainer in enumerate(trainers):
        db.session.add(LecturerCertificate(
            instance_id=inst.id,
            trainer_id=trainer.id, number=f'BA-{i}', recipient_name='Т',
            event_title='Захід', issued_at=early + timedelta(seconds=i),
        ))
    db.session.commit()
    cert = _pending_with_address('tc-after-addressless@test.com')

    sent, skipped = lc_svc.send_pending()

    assert sent == 1
    assert skipped == 55
    db.session.refresh(cert)
    assert cert.emailed_at is not None


def test_orphan_certificates_are_not_queued(app, enabled_mail):
    """Сирота (trainer_id IS NULL) -- ні в черзі, ні в ліміті, ні в звіті:
    з ним нічого не можна зробити."""
    inst = make_instance(make_course(), days=-3, status='completed')
    early = utcnow() - timedelta(days=2)
    for i in range(55):
        # Два NULL у trainer_id не порушують unique-пари -- так само, як
        # після видалення двох тренерів одного заходу.
        db.session.add(LecturerCertificate(
            instance_id=inst.id,
            trainer_id=None, number=f'OR-{i}', recipient_name='Т',
            event_title='Захід', issued_at=early + timedelta(seconds=i),
        ))
    db.session.commit()
    cert = _pending_with_address('tc-after-orphans@test.com')

    sent, skipped = lc_svc.send_pending()

    assert (sent, skipped) == (1, 0)
    db.session.refresh(cert)
    assert cert.emailed_at is not None

    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_report') as report:
        stats = lc_svc.daily_maintenance()
    assert stats['stuck'] == 0
    assert not report.called


# ---------------------------------------------------------------------------
# issue_missing / daily_maintenance: страхувальна сітка на два реальні
# сценарії, де тригер видачі (рівно один раз, на переході в completed) не
# встигає видати документ.
# ---------------------------------------------------------------------------
def test_issue_missing_picks_up_instance_after_points_added(app):
    inst, _ = _completed_instance(points=None, trainers=1)
    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_failed'):
        assert lc_svc.issue_for_instance(inst) == []
    inst.course.bpr_lecturer_points = 4
    db.session.commit()
    assert lc_svc.issue_missing() == 1
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 1


def test_issue_missing_picks_up_trainer_added_later(app):
    inst, _ = _completed_instance(trainers=1)
    lc_svc.issue_for_instance(inst)
    extra = make_trainer(name='Пізній Т.')
    set_trainers(inst.course, [t.id for t in inst.course.trainers] + [extra.id])
    db.session.commit()
    lc_svc.issue_missing()
    assert LecturerCertificate.query.filter_by(
        instance_id=inst.id, trainer_id=extra.id).count() == 1


def test_blocked_report_covers_all_three_preconditions(app):
    """Звіт мусить ловити не лише відсутні бали.

    Передумов три, і захід без номера провайдера БПР так само не видасть
    жодного сертифіката, як і захід без балів -- тільки мовчки. Тест
    перевіряє всі три, а не лише провайдера: `blocking_reason` питає
    `certificate_service` двома окремими викликами
    (`_bpr_number_inputs`, `_lecturer_points`), і кожен мусить дійти до
    свого власного тексту причини.
    """
    from app.models.site_settings import SiteSettings

    inst, _ = _completed_instance(trainers=1)

    # Колонка NOT NULL (default '') -- порожній рядок, а не None, як і в
    # test_missing_provider_number_issues_nothing_and_notifies_admins вище.
    SiteSettings.get().bpr_provider_number = ''
    db.session.commit()
    reason = lc_svc.blocking_reason(inst)
    assert reason is not None
    assert 'провайдера' in reason

    SiteSettings.get().bpr_provider_number = '2738'
    inst.course.bpr_event_number = ''
    db.session.commit()
    reason = lc_svc.blocking_reason(inst)
    assert reason is not None
    assert 'заходу' in reason

    inst.course.bpr_event_number = '4999999'
    inst.course.bpr_lecturer_points = None
    db.session.commit()
    reason = lc_svc.blocking_reason(inst)
    assert reason is not None
    assert 'бали' in reason


def test_daily_maintenance_sends_no_report_when_clean(app):
    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_report') as report:
        lc_svc.daily_maintenance()
    assert not report.called


def test_daily_maintenance_flags_certificate_stuck_after_24_hours(app):
    """Сертифікат, виданий понад добу тому й досі `emailed_at IS NULL`,
    потрапляє у `stuck` -- саме ці записи задача 5 свідомо лишає
    непозначеними, щоб їх підхопив щоденний звіт."""
    inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(inst)[0]
    cert.issued_at = utcnow() - timedelta(hours=25)
    db.session.commit()

    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_report') as report:
        stats = lc_svc.daily_maintenance()

    assert stats['stuck'] == 1
    assert report.called
    stuck_arg = report.call_args.args[0]
    assert [c.id for c in stuck_arg] == [cert.id]


def test_daily_maintenance_does_not_flag_certificate_within_24_hours(app):
    """Межа STUCK_AFTER_HOURS: сертифікат, виданий менш ніж добу тому, ще
    НЕ вважається застряглим -- йому лишається шанс на звичайний
    5-хвилинний тік розсилки. Без цього теста регресія `<` на `<=`
    (чи навпаки) або загублений фільтр `emailed_at IS NULL` пройшли б
    непомітно."""
    inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(inst)[0]
    cert.issued_at = utcnow() - timedelta(hours=23)
    db.session.commit()

    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_report') as report:
        stats = lc_svc.daily_maintenance()

    assert stats['stuck'] == 0
    assert not report.called


def test_daily_maintenance_sends_report_with_actual_stuck_and_blocked_records(app):
    """Звіт шлеться не лише «коли брудно» -- а й несе САМЕ ці записи, а не
    порожні списки чи самі лічильники."""
    stuck_inst, _ = _completed_instance(trainers=1)
    cert = lc_svc.issue_for_instance(stuck_inst)[0]
    cert.issued_at = utcnow() - timedelta(hours=25)

    blocked_inst, _ = _completed_instance(points=None, trainers=1)
    db.session.commit()

    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_failed'), \
         patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_report') as report:
        stats = lc_svc.daily_maintenance()

    assert stats == {'issued': 0, 'stuck': 1, 'blocked': 1}
    report.assert_called_once()
    stuck_arg, blocked_arg = report.call_args.args
    assert [c.id for c in stuck_arg] == [cert.id]
    assert [inst.id for inst, _reason in blocked_arg] == [blocked_inst.id]
    assert 'бали' in blocked_arg[0][1]


def test_daily_maintenance_excludes_fully_issued_instance_from_blocked(app):
    """Захід, де сертифікати вже видані ВСІМ тренерам, не має щодня влучати
    у звіт як «потребує уваги», навіть якщо номер провайдера спорожнів уже
    ПІСЛЯ видачі -- добирати там нічого, а постійний шум привчає не читати
    звіт узагалі."""
    from app.models.site_settings import SiteSettings

    inst, _ = _completed_instance(trainers=1)
    lc_svc.issue_for_instance(inst)
    SiteSettings.get().bpr_provider_number = ''
    db.session.commit()

    assert lc_svc.blocking_reason(inst) is not None  # передумова й справді порушена

    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_report') as report:
        stats = lc_svc.daily_maintenance()

    assert stats['blocked'] == 0
    assert not report.called


# ---------------------------------------------------------------------------
# Вікно автодобору (фінальна рецензія, C3): щоденна джоба не видає й не
# показує в «заблоковано» історичні заходи з імпорту.
# ---------------------------------------------------------------------------
def _completed_days_ago(days, points=5):
    inst, made = _completed_instance(points=points, trainers=1)
    inst.start_date = utcnow() - timedelta(days=days)
    db.session.commit()
    return inst


def test_daily_maintenance_ignores_instance_outside_window(app):
    old = _completed_days_ago(lc_svc.LECTURER_AUTO_ISSUE_WINDOW_DAYS * 2)
    old_blocked = _completed_days_ago(
        lc_svc.LECTURER_AUTO_ISSUE_WINDOW_DAYS * 2, points=None)
    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_failed'),          patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_report') as report:
        stats = lc_svc.daily_maintenance()
    assert stats['issued'] == 0
    assert stats['blocked'] == 0
    assert not report.called
    assert LecturerCertificate.query.filter(
        LecturerCertificate.instance_id.in_([old.id, old_blocked.id])).count() == 0


def test_daily_maintenance_issues_for_instance_inside_window(app):
    recent = _completed_days_ago(5)
    stats = lc_svc.daily_maintenance()
    assert stats['issued'] == 1
    assert LecturerCertificate.query.filter_by(instance_id=recent.id).count() == 1


def test_window_uses_end_date_when_present(app):
    """Багатоденний захід: початок поза вікном, кінець -- у ньому."""
    inst = _completed_days_ago(lc_svc.LECTURER_AUTO_ISSUE_WINDOW_DAYS + 10)
    inst.end_date = utcnow() - timedelta(days=2)
    db.session.commit()
    assert lc_svc.issue_missing() == 1


def test_status_transition_is_not_limited_by_window(app):
    """Адмін, що свідомо переводить старий захід у 'completed', отримує
    видачу -- вікно стосується лише автоматичного добору."""
    inst = _completed_days_ago(lc_svc.LECTURER_AUTO_ISSUE_WINDOW_DAYS * 3)
    issued = lc_svc.on_status_changed(inst, 'published')
    assert len(issued) == 1


# ---------------------------------------------------------------------------
# on_status_changed (фінальна рецензія, I3): одна умова переходу на обидва
# маршрути.
# ---------------------------------------------------------------------------
def test_on_status_changed_issues_only_on_transition_into_completed(app):
    inst, _ = _completed_instance(trainers=1)
    assert lc_svc.on_status_changed(inst, 'completed') == []
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 0
    inst.status = 'published'
    assert lc_svc.on_status_changed(inst, 'draft') == []
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 0
    inst.status = 'completed'
    assert len(lc_svc.on_status_changed(inst, 'published')) == 1


# ---------------------------------------------------------------------------
# Звіт адмінам (фінальна рецензія, I4): справжня причина біля кожного заходу.
# ---------------------------------------------------------------------------
def test_report_names_real_reason_for_each_blocked_instance(app, enabled_mail):
    from markupsafe import escape

    no_points, _ = _completed_instance(points=None, trainers=1)
    no_number, _ = _completed_instance(trainers=1)
    no_number.course.bpr_event_number = ''
    db.session.commit()
    blocked = [(no_points, lc_svc.blocking_reason(no_points)),
               (no_number, lc_svc.blocking_reason(no_number))]

    with patch('app.services.notification_recipients.resolve',
               return_value=['tc-report-admin@test.com']):
        EmailService.notify_lecturer_certificate_report([], blocked)

    log = EmailLog.query.filter_by(to_email='tc-report-admin@test.com').one()
    assert 'без балів' not in log.subject
    assert 'заблоковано' in log.subject
    # Причини містять '->' -- у листі вони HTML-екрановані автоескейпом.
    assert str(escape(blocked[0][1])) in log.html_body
    assert str(escape(blocked[1][1])) in log.html_body


def test_daily_maintenance_does_not_resend_failure_letter_for_blocked(app):
    """Заблокований захід -- лише у щоденному звіті, без окремого листа «не видано».

    Лист «не видано» вже пішов адмінам у мить завершення заходу. Якби
    щоденна джоба пробувала видачу знову, кожного ранку до звіту додавався б
    ще один такий лист на кожен заблокований захід -- два листи про одне й те
    саме щодня, аж до кінця вікна добору.
    """
    inst, _ = _completed_instance(points=None, trainers=1)
    with patch('app.services.email_service.EmailService'
               '.notify_lecturer_certificate_failed') as failed, \
            patch('app.services.email_service.EmailService'
                  '.notify_lecturer_certificate_report') as report:
        stats = lc_svc.daily_maintenance()
    assert not failed.called
    assert report.call_count == 1
    assert stats['blocked'] == 1
    assert stats['issued'] == 0


class _QueryCounter:
    """Рахує SQL-запити до БД у межах блоку with."""

    def __enter__(self):
        from sqlalchemy import event
        self.count = 0
        self._engine = db.engine
        event.listen(self._engine, 'before_cursor_execute', self._inc)
        return self

    def _inc(self, *args, **kwargs):
        self.count += 1

    def __exit__(self, *exc):
        from sqlalchemy import event
        event.remove(self._engine, 'before_cursor_execute', self._inc)


def test_send_pending_scans_addressless_queue_without_per_record_queries(app):
    """Безадресні сертифікати лишаються в черзі назавжди й скануються щотіку.

    Ліниві звʼязки давали кілька запитів на кожен такий запис, і тік раз на
    п'ять хвилин ставав дорожчим із кожним новим тренером без пошти. Ціна
    сканування мусить не залежати від довжини черги.
    """
    for _ in range(12):
        inst, _ = _completed_instance(trainers=1)
        lc_svc.issue_for_instance(inst)
    with _QueryCounter() as counter:
        sent, skipped = lc_svc.send_pending()
    assert (sent, skipped) == (0, 12)
    assert counter.count <= 3, counter.count


def test_missing_trainers_lookup_does_not_grow_with_instances(app):
    """Добір ходить по всіх завершених заходах вікна; тренери дати й курсу
    мусять вантажитись наперед, а не по три запити на кожен захід."""
    for _ in range(6):
        _completed_instance(trainers=2)
    db.session.expire_all()
    with _QueryCounter() as counter:
        instances = lc_svc._completed_instances()
        missing = lc_svc._missing_trainers_by_instance(instances)
        for inst in instances:
            lc_svc.blocking_reason(inst)
    assert len(missing) >= 6
    assert counter.count <= 8, counter.count
