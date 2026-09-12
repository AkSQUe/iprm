"""Номер заходу БПР у картці проведення: поле, підказка, збереження, застереження.

Номер реєстру виписують на кожне подання окремо, тож поле живе на даті, а
курсове лишається відкатом. Застереження потрібне через перехід: у частини
дат сертифікати вже видані під СТАРИМ (курсовим) номером, і адмін мусить
бачити це до того, як вписати новий.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import certificate_service
from tests.support.rbac import grant_role


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def instance(app):
    course = Course(title='Базовий курс', slug=f'bnum-{_uid()}',
                    short_description='d', is_active=True, base_price=100,
                    cpd_points_online=12, cpd_points_offline=12,
                    bpr_event_number='1028974')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        start_date=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _form(app, instance):
    from app.admin.forms import CourseInstanceForm
    from app.admin.routes_instances import _populate_choices

    with app.test_request_context():
        form = CourseInstanceForm(obj=instance)
        _populate_choices(form, instance=instance)
    return form


def _save(app, instance, number):
    from app.services import course_service

    with app.test_request_context():
        form = _form(app, instance)
        form.bpr_event_number.data = number
        course_service.populate_instance_from_form(instance, form)
    return instance


class TestForm:
    def test_field_is_optional(self, app, instance):
        form = _form(app, instance)
        assert not form.bpr_event_number.flags.required

    def test_placeholder_names_the_inherited_number(self, app, instance):
        """Порожнє поле мусить казати, який номер піде в сертифікат, --
        інакше це доводилось би перевіряти в картці курсу."""
        form = _form(app, instance)
        assert form.bpr_event_number.render_kw['placeholder'] == '1028974 (з курсу)'

    def test_placeholder_is_generic_when_the_course_has_no_number(self, app, instance):
        instance.course.bpr_event_number = None
        db.session.flush()
        form = _form(app, instance)
        assert form.bpr_event_number.render_kw['placeholder'] == '7 цифр'


class TestSaving:
    def test_own_number_overrides_the_course(self, app, instance):
        _save(app, instance, '1031500')
        assert instance.bpr_event_number == '1031500'
        assert instance.effective_bpr_event_number == '1031500'

    def test_blank_clears_to_none_and_falls_back(self, app, instance):
        instance.bpr_event_number = '1031500'
        db.session.flush()
        _save(app, instance, '   ')
        assert instance.bpr_event_number is None
        assert instance.effective_bpr_event_number == '1028974'


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'bnum-adm-{_uid()}@test.com', 'password123',
        first_name='A', last_name='D', email_confirmed=True)
    grant_role(user, 'super_admin')
    db.session.flush()
    return user


@pytest.fixture
def _no_pdf(monkeypatch):
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')


def _issue(instance):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    user = User.create_with_password(
        f'bnum-{_uid()}@test.com', 'password123',
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
    return certificate_service.issue_certificate(reg)


class TestIssuedWarning:
    def test_no_certificates_means_nothing_to_warn_about(self, app, instance):
        assert certificate_service.issued_event_numbers(instance) == (0, [])

    def test_reports_count_and_the_numbers_actually_printed(self, app, instance, _no_pdf):
        """Сегмент читаємо з самого номера сертифіката, а не з поточного поля:
        показати треба те, що вже пішло в реєстр і на руки людині."""
        cert = _issue(instance)
        db.session.flush()

        count, numbers = certificate_service.issued_event_numbers(instance)

        assert count == 1
        assert numbers == ['1028974']
        assert cert.number.split('-')[2] == '1028974'

    def test_editor_warns_before_the_number_is_changed(self, app, client, instance,
                                                       _no_pdf, admin):
        _issue(instance)
        db.session.flush()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)

        html = client.get(
            f'/admin/instances/{instance.id}/edit').get_data(as_text=True)

        assert 'уже видано' in html
        assert '1028974' in html

    def test_change_is_allowed_despite_issued_certificates(self, app, instance, _no_pdf):
        """Застереження -- не замок: опечатку в номері мусить бути чим виправити."""
        _issue(instance)
        _save(app, instance, '1031500')
        assert instance.bpr_event_number == '1031500'
