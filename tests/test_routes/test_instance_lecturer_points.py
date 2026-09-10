"""Бали БПР лектору -- перевизначення на рівні проведення.

Норма лектора жила лише на курсі, тож усі його дати давали однаково. Але та
сама програма в один день іде повним днем, а в інший -- скороченим блоком, і
лекторська норма за неї інша. Порожнє поле проведення означає «як у курсу»
(CourseInstance.effective_lecturer_points), а не «нуль балів»: сплутати ці
два стани означає видати сертифікат із нулем замість відмови.

Окремо тримається інша межа: сертифікат, виданий тренеру, якого потім
прибрали зі складу, мусить лишатись досяжним. Документ із номером уже на
руках у людини, і зникнути з адмінки він не може.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
    return make_super_admin(email=f'lp-admin-{uuid4().hex[:6]}@test.com')


@pytest.fixture(autouse=True)
def bpr_settings(app):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    settings.bpr_lecturer_counter = 0
    db.session.flush()
    return settings


def _trainer(name):
    trainer = Trainer(full_name=name, slug=f't-{uuid4().hex[:10]}')
    db.session.add(trainer)
    db.session.flush()
    return trainer


def _instance(course_points=Decimal('5'), own_points=None, trainer_ids=()):
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'lp-{uuid4().hex[:8]}',
        is_active=True, event_type='course',
        bpr_event_number=str(uuid4().int % 900000 + 100000),
        bpr_lecturer_points=course_points,
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ', bpr_lecturer_points=own_points,
        start_date=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.session.add(inst)
    db.session.flush()
    if trainer_ids:
        trainer_links.set_trainers(inst, list(trainer_ids))
        db.session.flush()
    return inst


class TestEffectiveLecturerPoints:
    def test_empty_field_falls_back_to_the_course(self):
        inst = _instance(course_points=Decimal('5'), own_points=None)
        assert inst.effective_lecturer_points == Decimal('5')

    def test_own_value_wins_over_the_course(self):
        inst = _instance(course_points=Decimal('5'), own_points=Decimal('2.5'))
        assert inst.effective_lecturer_points == Decimal('2.5')

    def test_explicit_zero_is_not_the_same_as_empty(self):
        """Нуль -- це рішення «за цю дату лектор не отримує балів», і воно
        НЕ має провалюватись у курсову норму."""
        inst = _instance(course_points=Decimal('5'), own_points=Decimal('0'))
        assert inst.effective_lecturer_points == Decimal('0')


class TestCertificateReadsTheInstance:
    def test_certificate_carries_the_instances_own_norm(self):
        trainer = _trainer('Лектор Л.')
        inst = _instance(course_points=Decimal('5'), own_points=Decimal('2.5'),
                         trainer_ids=[trainer.id])

        cert = certificate_service.issue_lecturer_certificate(inst, trainer)

        assert cert.cpd_points == Decimal('2.5')

    def test_without_a_norm_anywhere_it_refuses_instead_of_writing_zero(self):
        trainer = _trainer('Лектор Л.')
        inst = _instance(course_points=None, own_points=None,
                         trainer_ids=[trainer.id])

        with pytest.raises(ValueError):
            certificate_service.issue_lecturer_certificate(inst, trainer)


class TestIssuedCertificateOutlivesTheLineup:
    def test_removed_trainers_certificate_still_shows_up_in_the_form(
        self, client, admin, login_admin,
    ):
        login_admin(admin)
        gone, current = _trainer('Колишній К.'), _trainer('Чинний Ч.')
        inst = _instance(trainer_ids=[gone.id])
        cert = certificate_service.issue_lecturer_certificate(inst, gone)
        number = cert.number
        trainer_links.set_trainers(inst, [current.id])
        db.session.commit()

        html = client.get(f'/admin/instances/{inst.id}/edit').get_data(as_text=True)

        assert number in html
        assert 'більше не в складі' in html

    def test_removed_trainers_certificate_still_downloads(
        self, client, admin, login_admin,
    ):
        """Гвард складу обмежує ВИДАЧУ, а не завантаження вже виданого."""
        login_admin(admin)
        gone, current = _trainer('Колишній К.'), _trainer('Чинний Ч.')
        inst = _instance(trainer_ids=[gone.id])
        cert = certificate_service.issue_lecturer_certificate(inst, gone)
        cert_id = cert.id
        trainer_links.set_trainers(inst, [current.id])
        db.session.commit()

        response = client.post(
            f'/admin/instances/{inst.id}/lecturer-certificate',
            data={'cert_id': str(cert_id)},
        )

        assert response.status_code == 200
        assert response.mimetype == 'application/pdf'

    def test_certificate_of_another_instance_is_not_served(
        self, client, admin, login_admin,
    ):
        """cert_id перевіряється на належність саме цьому проведенню."""
        login_admin(admin)
        trainer = _trainer('Лектор Л.')
        mine = _instance(trainer_ids=[trainer.id])
        other = _instance(trainer_ids=[trainer.id])
        foreign = certificate_service.issue_lecturer_certificate(other, trainer)
        db.session.commit()

        response = client.post(
            f'/admin/instances/{mine.id}/lecturer-certificate',
            data={'cert_id': str(foreign.id)}, follow_redirects=True,
        )

        assert response.mimetype != 'application/pdf'
        assert 'Сертифікат не знайдено' in response.get_data(as_text=True)

    def test_issuing_still_requires_membership(self, client, admin, login_admin):
        login_admin(admin)
        stranger = _trainer('Чужий Ч.')
        own = _trainer('Свій С.')
        inst = _instance(trainer_ids=[own.id])
        db.session.commit()

        client.post(
            f'/admin/instances/{inst.id}/lecturer-certificate',
            data={'trainer_id': str(stranger.id)}, follow_redirects=True,
        )

        assert LecturerCertificate.query.filter_by(
            instance_id=inst.id, trainer_id=stranger.id,
        ).first() is None
