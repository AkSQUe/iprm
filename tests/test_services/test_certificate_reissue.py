"""Перевидача сертифіката після виправлення даних заходу.

Реєстр БПР видає номер на кожне подання, і адмін вписує його в проведення
вже після того, як сертифікати пішли людям. Видача -- незмінний знімок
(issue_certificate свідомо не переписує номер), тож для виправлення
потрібен окремий явний шлях: reissue_*.

Порядковий сегмент учасника при цьому ЗБЕРІГАЄТЬСЯ -- міняється лише те,
що виправив адмін (номер заходу, рік, знімки даних).
"""
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.models.user import User
from app.services import certificate_service


@pytest.fixture
def fake_pdf(monkeypatch):
    """Справжній запис файлу, але без weasyprint: рендер -- заглушка.

    Саме тому тут не мокається `_write_pdf`, як у сусідніх тестах: перевидача
    зобов'язана прибрати файл під старим номером, і це можна побачити лише
    на реальних файлах.
    """
    monkeypatch.setattr(certificate_service, 'render_pdf_bytes',
                        lambda cert, **kw: b'%PDF-1.4 fake')


@pytest.fixture
def provider(app):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    db.session.commit()
    return settings


@pytest.fixture
def cert_folder(app, tmp_path):
    """PDF пишемо в тимчасову теку, а не в проектну /certificates."""
    previous = app.config['CERTIFICATE_FOLDER']
    app.config['CERTIFICATE_FOLDER'] = str(tmp_path)
    yield tmp_path
    app.config['CERTIFICATE_FOLDER'] = previous


def _course(event_number='1028974', title=None):
    course = Course(
        title=title or f'Курс {uuid4().hex[:4]}', slug=f'reis-{uuid4().hex[:6]}',
        is_active=True, event_type='course',
        cpd_points_online=12, cpd_points_offline=12,
        bpr_event_number=event_number,
        bpr_lecturer_points=5,
    )
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, event_number=None):
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ', bpr_event_number=event_number,
        start_date=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _registration(instance):
    user = User.create_with_password(
        f'reis-{uuid4().hex[:6]}@test.com', 'password123',
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
    return reg


def _trainer(name='Тренер Тренерович'):
    trainer = Trainer(full_name=name, full_name_dative='Тренеру Тренеровичу',
                      slug=f'trainer-{uuid4().hex[:6]}')
    db.session.add(trainer)
    db.session.flush()
    return trainer


def _event_segment(number):
    """РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ -> ЗЗЗЗЗЗЗ."""
    return number.split('-')[2]


def _participant_segment(number):
    """РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ -> УУУУУУ."""
    return number.split('-')[3]


# ---- Учасницький ----
def test_reissue_picks_up_corrected_instance_number(app, provider, fake_pdf,
                                                    cert_folder):
    instance = _instance(_course('1028974'), event_number=None)
    reg = _registration(instance)
    db.session.commit()
    cert = certificate_service.issue_certificate(reg)
    assert _event_segment(cert.number) == '1028974'

    instance.bpr_event_number = '1031500'
    db.session.commit()

    cert = certificate_service.reissue_certificate(reg)

    assert _event_segment(cert.number) == '1031500'


def test_reissue_keeps_participant_segment(app, provider, fake_pdf, cert_folder):
    instance = _instance(_course('1028974'))
    reg = _registration(instance)
    db.session.commit()
    cert = certificate_service.issue_certificate(reg)
    issued_segment = _participant_segment(cert.number)

    instance.bpr_event_number = '1031500'
    db.session.commit()
    cert = certificate_service.reissue_certificate(reg)

    assert _participant_segment(cert.number) == issued_segment


def test_reissue_refreshes_snapshots(app, provider, fake_pdf, cert_folder):
    course = _course('1028974', title='Стара назва')
    instance = _instance(course)
    reg = _registration(instance)
    db.session.commit()
    certificate_service.issue_certificate(reg)

    course.title = 'Виправлена назва'
    instance.location = 'Харків'
    db.session.commit()

    cert = certificate_service.reissue_certificate(reg)

    assert cert.event_title == 'Виправлена назва'
    assert cert.event_place == 'Харків'


def test_reissue_writes_new_pdf_and_removes_the_old_one(app, provider, fake_pdf,
                                                        cert_folder):
    instance = _instance(_course('1028974'))
    reg = _registration(instance)
    db.session.commit()
    cert = certificate_service.issue_certificate(reg)
    old_path = certificate_service.certificate_abs_path(cert)
    assert os.path.exists(old_path)

    instance.bpr_event_number = '1031500'
    db.session.commit()
    cert = certificate_service.reissue_certificate(reg)

    new_path = certificate_service.certificate_abs_path(cert)
    assert new_path != old_path
    assert os.path.exists(new_path)
    assert not os.path.exists(old_path)


def test_reissue_prints_the_new_number_inside_the_pdf(app, provider, monkeypatch,
                                                      cert_folder):
    """Ім'я файлу -- не документ: номер мусить змінитись у самому рендері."""
    rendered = []
    monkeypatch.setattr(certificate_service, 'render_pdf_bytes',
                        lambda cert, **kw: rendered.append(cert.number) or b'%PDF')
    instance = _instance(_course('1028974'))
    reg = _registration(instance)
    db.session.commit()
    certificate_service.issue_certificate(reg)
    instance.bpr_event_number = '1031500'
    db.session.commit()

    cert = certificate_service.reissue_certificate(reg)

    assert rendered[-1] == cert.number
    assert _event_segment(rendered[-1]) == '1031500'


def test_reissue_without_changes_keeps_the_number(app, provider, fake_pdf,
                                                  cert_folder):
    """Повторне натискання нічого не псує: номер той самий, файл на місці."""
    instance = _instance(_course('1028974'))
    reg = _registration(instance)
    db.session.commit()
    issued = certificate_service.issue_certificate(reg).number

    cert = certificate_service.reissue_certificate(reg)

    assert cert.number == issued
    assert os.path.exists(
        certificate_service.certificate_abs_path(cert))


def test_reissue_requires_an_issued_certificate(app, provider, fake_pdf,
                                                cert_folder):
    reg = _registration(_instance(_course('1028974')))
    db.session.commit()

    with pytest.raises(ValueError, match='не видано'):
        certificate_service.reissue_certificate(reg)


def test_reissue_refuses_when_new_number_is_taken(app, provider, fake_pdf,
                                                  cert_folder):
    """Чужий номер не перезаписуємо мовчки -- це вже ручна правка БД."""
    course = _course('1028974')
    first = _registration(_instance(course, event_number='1031500'))
    second_instance = _instance(course, event_number='1028974')
    second = _registration(second_instance)
    db.session.commit()
    first_cert = certificate_service.issue_certificate(first)
    second_cert = certificate_service.issue_certificate(second)

    # Займаємо номер, який дістанеться другому після виправлення.
    year, prov, _event, participant = second_cert.number.split('-')
    first_cert.number = f'{year}-{prov}-1031500-{participant}'
    second_instance.bpr_event_number = '1031500'
    db.session.commit()

    with pytest.raises(ValueError, match='зайнятий'):
        certificate_service.reissue_certificate(second)


def test_reissue_refuses_revoked_certificate(app, provider, fake_pdf, cert_folder):
    """Відкликаний видають наново через «Видати», а не перевидають."""
    instance = _instance(_course('1028974'))
    reg = _registration(instance)
    db.session.commit()
    cert = certificate_service.issue_certificate(reg)
    cert.revoked = True
    db.session.commit()

    with pytest.raises(ValueError, match='відкликан'):
        certificate_service.reissue_certificate(reg)


def test_reissue_still_demands_the_event_number(app, provider, fake_pdf,
                                                cert_folder):
    """Номер прибрали й з дати, і з курсу -- перевидати нема під чим."""
    course = _course('1028974')
    instance = _instance(course)
    reg = _registration(instance)
    db.session.commit()
    certificate_service.issue_certificate(reg)

    course.bpr_event_number = None
    db.session.commit()

    with pytest.raises(ValueError, match='номер заходу БПР'):
        certificate_service.reissue_certificate(reg)


def test_reissue_number_stays_unique_in_db(app, provider, fake_pdf, cert_folder):
    instance = _instance(_course('1028974'))
    reg = _registration(instance)
    db.session.commit()
    certificate_service.issue_certificate(reg)
    instance.bpr_event_number = '1031500'
    db.session.commit()

    cert = certificate_service.reissue_certificate(reg)

    rows = db.session.query(Certificate.number).filter_by(number=cert.number).all()
    assert len(rows) == 1


# ---- Лекторський ----
def _lecturer_instance(event_number='1028974'):
    """Проведення з одним тренером у складі -- і сам тренер.

    Захід може мати кількох лекторів, тож видача й перевидача адресують
    конкретного: тести повертають пару, щоб не вгадувати «головного».
    """
    from app.services import trainer_links

    course = _course(event_number)
    instance = _instance(course, event_number=None)
    trainer = _trainer()
    trainer_links.set_trainers(instance, [trainer.id])
    db.session.commit()
    return instance, trainer


def test_lecturer_reissue_picks_up_corrected_number(app, provider, fake_pdf,
                                                    cert_folder):
    instance, trainer = _lecturer_instance('1028974')
    cert = certificate_service.issue_lecturer_certificate(instance, trainer)
    assert _event_segment(cert.number) == '1028974'

    instance.bpr_event_number = '1031500'
    db.session.commit()

    cert = certificate_service.reissue_lecturer_certificate(instance, trainer)

    assert _event_segment(cert.number) == '1031500'


def test_lecturer_reissue_keeps_lecturer_number_range(app, provider, fake_pdf,
                                                      cert_folder):
    """Лекторський діапазон 1xxxxx зберігається разом із порядковим сегментом."""
    instance, trainer = _lecturer_instance('1028974')
    issued = certificate_service.issue_lecturer_certificate(instance, trainer).number
    instance.bpr_event_number = '1031500'
    db.session.commit()

    cert = certificate_service.reissue_lecturer_certificate(instance, trainer)

    assert _participant_segment(cert.number) == _participant_segment(issued)
    assert _participant_segment(cert.number).startswith('1')


def test_lecturer_reissue_refreshes_snapshots(app, provider, fake_pdf, cert_folder):
    instance, trainer = _lecturer_instance('1028974')
    certificate_service.issue_lecturer_certificate(instance, trainer)

    instance.location = 'Харків'
    instance.course.bpr_lecturer_points = 16
    db.session.commit()

    cert = certificate_service.reissue_lecturer_certificate(instance, trainer)

    assert cert.event_place == 'Харків'
    assert int(cert.cpd_points) == 16


def test_lecturer_reissue_requires_an_issued_certificate(app, provider, fake_pdf,
                                                         cert_folder):
    instance, trainer = _lecturer_instance('1028974')

    with pytest.raises(ValueError, match='не видано'):
        certificate_service.reissue_lecturer_certificate(instance, trainer)
