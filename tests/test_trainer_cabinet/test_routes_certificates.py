"""Розділ сертифікатів у кабінеті тренера."""
from itertools import count

import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.services import lecturer_certificates as lc_svc
from app.services.trainer_links import set_trainers
from tests.test_trainer_cabinet._factories import (
    login, make_course, make_instance, make_trainer, make_user,
)

# Власний лічильник номерів заходів БПР, як у test_lecturer_certificates.py:
# issue_for_instance комітить сам, а деякі тести тут викликають фабрику
# двічі (свій + чужий сертифікат), тож номери мають не збігатися в межах
# одного тесту.
_event_numbers = count(6000000)


@pytest.fixture(autouse=True)
def bpr_settings(app):
    """Номер провайдера БПР -- без нього issue_for_instance падає ще до
    видачі жодного сертифіката (_bpr_number_inputs), а брифу цей рядок
    бракувало."""
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    db.session.flush()


def _trainer_with_certificate():
    user = make_user()
    trainer = make_trainer(user, name='Сертифікований Т.')
    course = make_course('Курс із сертифікатом')
    course.bpr_event_number = str(next(_event_numbers))
    set_trainers(course, [trainer.id])
    course.bpr_lecturer_points = 6
    inst = make_instance(course, days=-3, status='completed')
    db.session.commit()
    cert = lc_svc.issue_for_instance(inst)[0]
    return user, trainer, cert


def test_anonymous_redirected_to_login(client):
    resp = client.get('/trainer/certificates')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_user_without_card_gets_404(client):
    login(client, make_user())
    assert client.get('/trainer/certificates').status_code == 404


def test_section_lists_own_certificate(client):
    user, _, cert = _trainer_with_certificate()
    login(client, user)
    resp = client.get('/trainer/certificates')
    assert resp.status_code == 200
    assert cert.number.encode() in resp.data


def test_section_does_not_list_foreign_certificate(client):
    _, _, foreign = _trainer_with_certificate()
    other_user = make_user()
    make_trainer(other_user, name='Чужий Т.')
    login(client, other_user)
    resp = client.get('/trainer/certificates')
    assert resp.status_code == 200
    assert foreign.number.encode() not in resp.data


def test_download_own_certificate_returns_pdf(client):
    user, _, cert = _trainer_with_certificate()
    login(client, user)
    resp = client.get(f'/trainer/certificates/{cert.id}/download')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.data[:4] == b'%PDF'


def test_download_foreign_certificate_is_404(client):
    _, _, foreign = _trainer_with_certificate()
    other_user = make_user()
    make_trainer(other_user, name='Чужий Т. 2')
    login(client, other_user)
    resp = client.get(f'/trainer/certificates/{foreign.id}/download')
    assert resp.status_code == 404


def test_report_error_notifies_curator(client):
    from unittest.mock import patch

    user, _, cert = _trainer_with_certificate()
    login(client, user)
    with patch('app.services.email_service.EmailService'
               '.send_lecturer_certificate_complaint') as notify:
        resp = client.post(f'/trainer/certificates/{cert.id}/report',
                           data={'message': 'Помилка в ПІБ'},
                           follow_redirects=True)
    assert resp.status_code == 200
    assert notify.called


def test_report_error_on_foreign_certificate_is_404(client):
    _, _, foreign = _trainer_with_certificate()
    other_user = make_user()
    make_trainer(other_user, name='Чужий Т. 3')
    login(client, other_user)
    resp = client.post(f'/trainer/certificates/{foreign.id}/report',
                       data={'message': 'X'})
    assert resp.status_code == 404
