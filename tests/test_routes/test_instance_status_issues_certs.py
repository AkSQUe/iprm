"""Перехід проведення в 'completed' видає сертифікати тренерам."""
from itertools import count

import pytest

from app.extensions import db
from app.models.lecturer_certificate import LecturerCertificate
from app.models.site_settings import SiteSettings
from app.services.trainer_links import set_trainers
from tests.support.rbac import make_super_admin, switch_user
from tests.test_trainer_cabinet._factories import (
    make_course, make_instance, make_trainer,
)

# Власний лічильник номерів заходів БПР, аби не перетнутися з іншими
# файлами тестів (issue_lecturer_certificate комітить сам, тож номер живе
# й після rollback db_session -- див. test_lecturer_certificates.py).
_event_numbers = count(4200000)


@pytest.fixture(autouse=True)
def bpr_settings(app):
    """Номер провайдера БПР -- без нього видача впаде ще до перевірки балів,
    а тут перевіряється сам факт виклику видачі з маршруту, а не її правила."""
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    db.session.flush()
    return settings


def _setup(client, points=5):
    admin = make_super_admin(email='tc-inst-admin@test.com')
    db.session.commit()
    switch_user(client, admin)
    course = make_course()
    course.bpr_event_number = str(next(_event_numbers))
    trainer = make_trainer(name='Лектор Л.')
    set_trainers(course, [trainer.id])
    course.bpr_lecturer_points = points
    inst = make_instance(course, days=-2, status='active')
    db.session.commit()
    return inst, trainer


def test_completing_instance_issues_certificate(client):
    inst, trainer = _setup(client)
    resp = client.post(f'/admin/instances/{inst.id}/status',
                       data={'status': 'completed'})
    assert resp.status_code in (200, 302)
    cert = LecturerCertificate.query.filter_by(
        instance_id=inst.id, trainer_id=trainer.id).one()
    assert cert.emailed_at is None


def test_failed_transition_issues_nothing(client):
    inst, _ = _setup(client)
    client.post(f'/admin/instances/{inst.id}/status', data={'status': 'bogus'})
    assert LecturerCertificate.query.filter_by(instance_id=inst.id).count() == 0
