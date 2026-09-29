"""Перенумерація сертифікатів заходу з одиниці.

Сертифікати, видані за старим загальним лічильником, мають порядкові номери
не свого заходу: 15.08 отримав 1-6, а 12.09 продовжив із 7. Перенумерація --
разова явна дія: номери заходу стають щільними з 000001 (тренери з 100001),
не зачіпаючи номери інших проведень того самого заходу.
"""
import os
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.certificate_number_counter import CertificateNumberCounter
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.lecturer_certificate import LecturerCertificate
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.models.user import User
from app.services import certificate_service

PROVIDER = '2738'
YEAR = 2026

# Рядки комітяться й переживають тест: у кожного тесту свої номери заходів.
_event_numbers = count(1600000)


@pytest.fixture(autouse=True)
def provider(app):
    SiteSettings.get().bpr_provider_number = PROVIDER
    db.session.commit()


@pytest.fixture
def cert_folder(app, tmp_path, monkeypatch):
    """Справжні файли в тимчасовій теці, рендер -- заглушка."""
    previous = app.config['CERTIFICATE_FOLDER']
    app.config['CERTIFICATE_FOLDER'] = str(tmp_path)
    monkeypatch.setattr(certificate_service, 'render_pdf_bytes',
                        lambda cert, **kw: b'%PDF-1.4 fake')
    yield tmp_path
    app.config['CERTIFICATE_FOLDER'] = previous


def _instance(event_number):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'renum-{uuid4().hex[:6]}',
        is_active=True, event_type='course',
        cpd_points_online=12, cpd_points_offline=12,
        bpr_event_number=event_number, bpr_lecturer_points=5,
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ', start_date=datetime(YEAR, 9, 12, 9, tzinfo=timezone.utc),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _sibling(instance):
    """Друга дата того самого курсу -- успадковує той самий номер заходу."""
    inst = CourseInstance(
        course_id=instance.course_id, status='completed', event_format='offline',
        location='Київ', start_date=instance.start_date - timedelta(days=28),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _legacy_cert(instance, segment, revoked=False):
    """Сертифікат з номером, виданим ще за загальним лічильником."""
    user = User.create_with_password(
        f'renum-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True,
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='completed',
        payment_status='paid', attended=True,
    )
    db.session.add(reg)
    db.session.flush()
    number = Certificate.format_number(
        YEAR, PROVIDER, instance.effective_bpr_event_number, segment)
    cert = Certificate(
        registration_id=reg.id, user_id=user.id, number=number,
        recipient_name='Тест Тестовий', event_title='Захід',
        pdf_path=f'{YEAR}/{number}.pdf', revoked=revoked,
        issued_at=datetime(YEAR, 9, 13, tzinfo=timezone.utc),
    )
    db.session.add(cert)
    db.session.flush()
    return cert


def _legacy_lecturer_cert(instance, segment):
    trainer = Trainer(full_name='Тренер Тренерович', slug=f'renum-t-{uuid4().hex[:6]}')
    db.session.add(trainer)
    db.session.flush()
    cert = LecturerCertificate(
        instance_id=instance.id, trainer_id=trainer.id,
        number=Certificate.format_number(
            YEAR, PROVIDER, instance.effective_bpr_event_number, segment),
        recipient_name='Тренеру Тренеровичу', event_title='Захід',
        issued_at=datetime(YEAR, 9, 13, tzinfo=timezone.utc),
        emailed_at=datetime(YEAR, 9, 13, tzinfo=timezone.utc),
    )
    db.session.add(cert)
    db.session.flush()
    return cert


def _segments(certs):
    return [c.number[-6:] for c in certs]


# --- план ---------------------------------------------------------------------

def test_plan_numbers_the_event_from_one():
    instance = _instance(str(next(_event_numbers)))
    certs = [_legacy_cert(instance, s) for s in (7, 8, 9)]
    db.session.commit()

    plan = certificate_service.renumber_plan(instance)

    assert [(i.old_number[-6:], i.new_number[-6:]) for i in plan] == [
        ('000007', '000001'), ('000008', '000002'), ('000009', '000003'),
    ]
    assert [i.cert.id for i in plan] == [c.id for c in certs]


def test_plan_leaves_numbers_of_another_date_of_the_same_event():
    """Дві дати з успадкованим номером заходу -- для реєстру один захід:
    номери першої дати зайняті, друга продовжує за ними."""
    later = _instance(str(next(_event_numbers)))
    earlier = _sibling(later)
    for s in (1, 2, 3):
        _legacy_cert(earlier, s)
    for s in (4, 5):
        _legacy_cert(later, s)
    db.session.commit()

    assert not [i for i in certificate_service.renumber_plan(later)
                if i.old_number != i.new_number]
    assert not [i for i in certificate_service.renumber_plan(earlier)
                if i.old_number != i.new_number]


def test_plan_skips_numbers_held_by_other_dates():
    later = _instance(str(next(_event_numbers)))
    earlier = _sibling(later)
    _legacy_cert(earlier, 2)
    _legacy_cert(later, 5)
    _legacy_cert(later, 6)
    db.session.commit()

    plan = certificate_service.renumber_plan(later)

    assert [i.new_number[-6:] for i in plan] == ['000001', '000003']


def test_plan_covers_lecturers_in_their_range():
    instance = _instance(str(next(_event_numbers)))
    _legacy_lecturer_cert(instance, 100004)
    db.session.commit()

    (item,) = certificate_service.renumber_plan(instance)

    assert item.kind == 'lecturer'
    assert item.new_number.endswith('-100001')


def test_plan_needs_the_event_number():
    instance = _instance(None)
    db.session.commit()

    with pytest.raises(ValueError, match='номер заходу БПР'):
        certificate_service.renumber_plan(instance)


# --- перенумерація ------------------------------------------------------------

def test_renumber_rewrites_the_numbers(cert_folder):
    instance = _instance(str(next(_event_numbers)))
    certs = [_legacy_cert(instance, s) for s in (7, 8)]
    db.session.commit()

    changed = certificate_service.renumber_instance_certificates(instance)

    assert len(changed) == 2
    assert _segments(certs) == ['000001', '000002']
    assert [c.pdf_path for c in certs] == [f'{YEAR}/{c.number}.pdf' for c in certs]


def test_renumber_swaps_numbers_within_the_event(cert_folder):
    """Раніший за видачею тримає 000002, пізніший -- 000001: unique по
    номеру не дає обміняти їх напряму, без проміжного кроку."""
    instance = _instance(str(next(_event_numbers)))
    first = _legacy_cert(instance, 2)
    second = _legacy_cert(instance, 1)
    db.session.commit()

    certificate_service.renumber_instance_certificates(instance)

    assert _segments([first, second]) == ['000001', '000002']


def test_next_issue_continues_after_renumbering(cert_folder):
    """Лічильник заходу стає по новому хвосту: наступний -- 000003, а не 000010."""
    instance = _instance(str(next(_event_numbers)))
    for s in (7, 8):
        _legacy_cert(instance, s)
    prefix = Certificate.format_prefix(YEAR, PROVIDER, instance.effective_bpr_event_number)
    db.session.add(CertificateNumberCounter(prefix=prefix, kind='participant',
                                            last_value=9))
    db.session.commit()

    certificate_service.renumber_instance_certificates(instance)

    assert db.session.get(CertificateNumberCounter, (prefix, 'participant')).last_value == 2
    late = certificate_service._next_free_number(
        YEAR, PROVIDER, instance.effective_bpr_event_number)
    assert late.endswith('-000003')


def test_renumber_marks_a_new_version(cert_folder):
    instance = _instance(str(next(_event_numbers)))
    cert = _legacy_cert(instance, 7)
    lecturer = _legacy_lecturer_cert(instance, 100003)
    db.session.commit()
    before = cert.issued_at

    certificate_service.renumber_instance_certificates(instance)

    assert cert.issued_at != before
    assert lecturer.number.endswith('-100001')
    # Тренеру -- назад у чергу розсилки, як після поштучної перевидачі.
    assert lecturer.emailed_at is None


def test_renumber_keeps_revoked_certificate_revoked(cert_folder):
    instance = _instance(str(next(_event_numbers)))
    valid = _legacy_cert(instance, 7)
    revoked = _legacy_cert(instance, 8, revoked=True)
    db.session.commit()
    revoked_issued_at = revoked.issued_at

    certificate_service.renumber_instance_certificates(instance)

    assert _segments([valid, revoked]) == ['000001', '000002']
    assert revoked.revoked is True
    assert revoked.issued_at == revoked_issued_at


def test_renumber_removes_pdf_under_the_old_number(cert_folder):
    instance = _instance(str(next(_event_numbers)))
    cert = _legacy_cert(instance, 7)
    db.session.commit()
    certificate_service.regenerate_pdf(cert)
    old_path = certificate_service.certificate_abs_path(cert)
    assert os.path.exists(old_path)

    certificate_service.renumber_instance_certificates(instance)

    assert not os.path.exists(old_path)
    # Новий файл малюється при першому ж читанні.
    assert certificate_service.read_pdf_bytes(cert).startswith(b'%PDF')


def test_renumber_of_ordered_event_changes_nothing(cert_folder):
    instance = _instance(str(next(_event_numbers)))
    cert = _legacy_cert(instance, 1)
    db.session.commit()
    before = cert.issued_at

    assert certificate_service.renumber_instance_certificates(instance) == []
    assert cert.number.endswith('-000001')
    assert cert.issued_at == before


def test_background_mail_skips_revoked(cert_folder, monkeypatch):
    """Потік підмінено синхронним запуском: перевіряємо, КОМУ йде лист."""
    import threading
    from app.services.email_service import EmailService

    class _Inline:
        def __init__(self, target, **kwargs):
            self._target = target

        def start(self):
            self._target()

    sent = []
    monkeypatch.setattr(threading, 'Thread', _Inline)
    monkeypatch.setattr(EmailService, 'send_certificate',
                        staticmethod(lambda cert: sent.append(cert.id)))
    instance = _instance(str(next(_event_numbers)))
    valid = _legacy_cert(instance, 1)
    revoked = _legacy_cert(instance, 2, revoked=True)
    db.session.commit()

    certificate_service.email_certificates_in_background([valid.id, revoked.id])

    assert sent == [valid.id]


def test_renumber_leaves_other_dates_alone(cert_folder):
    later = _instance(str(next(_event_numbers)))
    earlier = _sibling(later)
    kept = _legacy_cert(earlier, 2)
    _legacy_cert(later, 5)
    db.session.commit()
    kept_number = kept.number

    certificate_service.renumber_instance_certificates(later)

    assert kept.number == kept_number
