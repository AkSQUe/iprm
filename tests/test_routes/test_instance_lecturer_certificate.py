"""Роут видачі лекторського сертифіката: тренер має належати заходу.

Захід може мати кількох тренерів (Task 8 плану "кілька тренерів"), кожен зі
своїм сертифікатом. Роут приймає `trainer_id` формою -- підміненого значення
(чужого тренера, якого в `instance.effective_trainers` немає) приймати не
можна: інакше хтось міг би через ручний POST видати сертифікат людині, яка
цей захід узагалі не вела.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.lecturer_certificate import LecturerCertificate
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.services import certificate_service, trainer_links
from tests.support.rbac import make_super_admin


@pytest.fixture
def login_admin(client):
    def _login(admin):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
            sess['_fresh'] = True
    return _login


@pytest.fixture
def admin(app):
    return make_super_admin(email=f'lc-admin-{uuid4().hex[:6]}@test.com')


@pytest.fixture(autouse=True)
def bpr_settings(app):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    settings.bpr_lecturer_counter = 0
    db.session.flush()
    return settings


def _trainer(name):
    t = Trainer(full_name=name, slug=f't-{uuid4().hex[:10]}')
    db.session.add(t)
    db.session.flush()
    return t


def _instance_with_trainer(trainer_id):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'cn-{uuid4().hex[:8]}',
        is_active=True, event_type='course',
        cpd_points_online=8, cpd_points_offline=8,
        bpr_event_number=str(uuid4().int % 900000 + 100000),
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
    trainer_links.set_trainers(inst, [trainer_id])
    db.session.flush()
    return inst


def test_rejects_trainer_not_among_the_events_trainers(client, admin, login_admin):
    login_admin(admin)
    own = _trainer('Свій лектор')
    stranger = _trainer('Чужий лектор')
    instance = _instance_with_trainer(own.id)
    db.session.commit()

    resp = client.post(
        f'/admin/instances/{instance.id}/lecturer-certificate',
        data={'trainer_id': stranger.id},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert LecturerCertificate.query.filter_by(instance_id=instance.id).count() == 0
    assert 'Оберіть лектора' in resp.get_data(as_text=True)


def test_rejects_missing_trainer_id(client, admin, login_admin):
    """Порожня форма -- та сама відмова, що й підмінений id."""
    login_admin(admin)
    own = _trainer('Свій лектор')
    instance = _instance_with_trainer(own.id)
    db.session.commit()

    resp = client.post(
        f'/admin/instances/{instance.id}/lecturer-certificate',
        data={}, follow_redirects=True,
    )

    assert resp.status_code == 200
    assert LecturerCertificate.query.filter_by(instance_id=instance.id).count() == 0


def test_edit_page_lists_a_row_per_trainer_with_issue_or_number(
        client, admin, login_admin, monkeypatch):
    """Рядок на кожного тренера: кнопка «Видати» -- поки нема сертифіката,
    номер -- коли вже є. «Видати всім» немає навмисно."""
    login_admin(admin)
    a, b = _trainer('Тренер А'), _trainer('Тренер Б')
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'cn-{uuid4().hex[:8]}',
        is_active=True, event_type='course',
        cpd_points_online=8, cpd_points_offline=8,
        bpr_event_number=str(uuid4().int % 900000 + 100000),
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
    trainer_links.set_trainers(instance, [a.id, b.id])
    db.session.flush()

    monkeypatch.setattr(
        certificate_service, 'render_lecturer_pdf', lambda lc: b'%PDF-fake%',
    )
    client.post(
        f'/admin/instances/{instance.id}/lecturer-certificate',
        data={'trainer_id': a.id},
    )
    cert_a = LecturerCertificate.query.filter_by(
        instance_id=instance.id, trainer_id=a.id,
    ).one()
    db.session.commit()

    html = client.get(f'/admin/instances/{instance.id}/edit').get_data(as_text=True)

    assert a.full_name in html
    assert b.full_name in html
    assert cert_a.number in html  # виданий -- номер видно
    assert 'Видати всім' not in html  # кнопки «видати всім» немає навмисно


def test_issues_for_a_trainer_that_belongs_to_the_event(
        client, admin, login_admin, monkeypatch):
    login_admin(admin)
    own = _trainer('Свій лектор')
    instance = _instance_with_trainer(own.id)
    db.session.commit()

    # PDF-рендер тут не тестуємо (WeasyPrint) -- лише те, що видача дійшла
    # до правильного тренера.
    monkeypatch.setattr(
        certificate_service, 'render_lecturer_pdf', lambda lc: b'%PDF-fake%',
    )

    resp = client.post(
        f'/admin/instances/{instance.id}/lecturer-certificate',
        data={'trainer_id': own.id},
    )

    assert resp.status_code == 200
    cert = LecturerCertificate.query.filter_by(instance_id=instance.id).one()
    assert cert.trainer_id == own.id
