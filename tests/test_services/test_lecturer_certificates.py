"""Автовидача сертифікатів лектора на захід."""
from itertools import count
from unittest.mock import patch

import pytest

from app.extensions import db
from app.models.lecturer_certificate import LecturerCertificate
from app.models.site_settings import SiteSettings
from app.services import lecturer_certificates as lc_svc
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
