"""Лекторський сертифікат -- кожному тренеру заходу окремо.

Захід може мати кількох тренерів (`CourseInstance.effective_trainers`, Task 2
плану "кілька тренерів"), і кожен читає лекцію особисто. Ключ ідемпотентності
`issue_lecturer_certificate` тому змінився з `instance_id` на пару
`(instance_id, trainer_id)`: трьом лекторам одного заходу належать три окремі
записи й номери, а не один запис для того, хто трапився першим у списку.
"""
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.lecturer_certificate import LecturerCertificate
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.models.user import User
from app.services import certificate_service, trainer_links


PROVIDER = '2738'

# Власний лічильник номерів заходів БПР -- щоб тести цього файлу не зіткнулися
# номерами сертифікатів із тестами test_certificate_number.py (issue_certificate
# комітить сам, тож його рядки переживають rollback фікстури db_session).
_event_numbers = count(3000000)


@pytest.fixture(autouse=True)
def bpr_settings(app):
    """Провайдер БПР заданий, лічильники з нуля -- як у test_certificate_number.py."""
    settings = SiteSettings.get()
    settings.bpr_provider_number = PROVIDER
    settings.bpr_participant_counter = 0
    settings.bpr_lecturer_counter = 0
    db.session.flush()
    return settings


@pytest.fixture
def no_pdf(monkeypatch):
    """Не малювати PDF учасницького сертифіката: WeasyPrint тут не тестуємо."""
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')


def _trainer(name):
    t = Trainer(full_name=name, slug=f't-{uuid4().hex[:10]}')
    db.session.add(t)
    db.session.flush()
    return t


def _instance_with_trainers(trainer_ids, cpd_points=8):
    """Проведення завершеного курсу з власним переліком тренерів у заданому
    порядку -- цей порядок і стає `position` у таблиці звʼязку."""
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'cn-{uuid4().hex[:8]}',
        is_active=True, event_type='course',
        cpd_points_online=cpd_points, cpd_points_offline=cpd_points,
        bpr_event_number=str(next(_event_numbers)),
        bpr_lecturer_points=5,
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ',
        start_date=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.session.add(inst)
    db.session.flush()
    trainer_links.set_trainers(inst, trainer_ids)
    db.session.flush()
    return inst


def _registration_for(instance, cpd_points=8):
    user = User.create_with_password(
        f'p-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Учасник', email_confirmed=True,
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


# --- декілька тренерів -> декілька сертифікатів ------------------------------

def test_three_trainers_get_three_numbers_in_position_order():
    """Номери йдуть за позицією тренера, а не за порядком натискань.

    Тренерів створюємо у порядку А, Б, В (зростаючі id), але в проведення
    записуємо у ПОРЯДКУ В, А, Б -- positions 0, 1, 2 відповідно. Якби видача
    йшла за id замість effective_trainers (position), результат був би іншим:
    саме тому id-порядок і порядок призначення тут навмисно розведені.
    """
    a, b, c = _trainer('Тренер А'), _trainer('Тренер Б'), _trainer('Тренер В')
    instance = _instance_with_trainers([c.id, a.id, b.id])

    ordered = instance.effective_trainers
    assert [t.id for t in ordered] == [c.id, a.id, b.id], (
        'фікстура зламана: позиції мають розходитися з порядком id, '
        'інакше тест нічого не доводить'
    )

    certs = [
        certificate_service.issue_lecturer_certificate(instance, trainer)
        for trainer in ordered
    ]
    numbers = [cert.number for cert in certs]

    assert len(set(numbers)) == 3, 'три тренери мусять отримати три різні номери'
    assert numbers == sorted(numbers), 'номери мають монотонно зростати за видачею'
    assert numbers[0].endswith('-100001')
    assert numbers[1].endswith('-100002')
    assert numbers[2].endswith('-100003')

    # Номер прив'язаний саме до того тренера, кому виданий -- у порядку
    # ПОЗИЦІЙ (В, А, Б), а не порядку створення записів у довіднику (А, Б, В).
    assert certs[0].trainer_id == c.id
    assert certs[1].trainer_id == a.id
    assert certs[2].trainer_id == b.id


def test_reissue_returns_the_same_number_per_trainer():
    """Ідемпотентність на новому ключі (instance_id, trainer_id)."""
    a, b = _trainer('Тренер А'), _trainer('Тренер Б')
    instance = _instance_with_trainers([a.id, b.id])

    first_a = certificate_service.issue_lecturer_certificate(instance, a)
    first_b = certificate_service.issue_lecturer_certificate(instance, b)
    assert first_a.number != first_b.number, 'різні тренери мають різні номери'

    again_a = certificate_service.issue_lecturer_certificate(instance, a)
    again_b = certificate_service.issue_lecturer_certificate(instance, b)

    assert again_a.id == first_a.id
    assert again_a.number == first_a.number
    assert again_b.id == first_b.id
    assert again_b.number == first_b.number

    # Повторна видача не витрачає лічильник -- нових записів не з'явилось.
    assert LecturerCertificate.query.filter_by(instance_id=instance.id).count() == 2


def test_missing_trainer_raises_value_error():
    """Захід без тренерів -- зрозуміла помилка, а не AttributeError."""
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'cn-{uuid4().hex[:8]}',
        is_active=True, event_type='course',
        cpd_points_online=8, cpd_points_offline=8,
        bpr_event_number=str(next(_event_numbers)),
        bpr_lecturer_points=5,
    )
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ',
        start_date=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.session.add(instance)
    db.session.flush()

    assert instance.effective_trainers == []
    with pytest.raises(ValueError, match='лектора'):
        certificate_service.issue_lecturer_certificate(
            instance, instance.effective_trainer,
        )


# --- учасницький сертифікат не змінився --------------------------------------

def test_participant_certificate_still_signed_by_the_first(no_pdf):
    """Учасницький сертифікат не змінює вигляд: підпис -- головного.

    `effective_trainer` -- перший з `effective_trainers` -- лишається єдиним
    джерелом імені лектора й підпису для УЧАСНИЦЬКОГО сертифіката, навіть
    коли захід веде кілька людей.
    """
    a, b, c = _trainer('Головна Лекторка'), _trainer('Друга'), _trainer('Третій')
    a.signature = 'images/trainers/a/signature.webp'
    instance = _instance_with_trainers([a.id, b.id, c.id])
    reg = _registration_for(instance)

    cert = certificate_service.issue_certificate(reg)

    assert cert.lecturer_name == a.full_name
    assert cert.lecturer_name != b.full_name
    assert cert.lecturer_name != c.full_name
    assert cert.lecturer_signature == a.signature
