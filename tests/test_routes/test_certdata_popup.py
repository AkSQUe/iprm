"""Плаваючий поп-ап «заповніть дані для сертифіката»: де він показується.

Виняткові розділи (кабінет, реєстрація, оплата, тестування) визначались через
`path.startswith('/quiz')`, і для ru/en це не спрацьовувало НІКОЛИ: auth,
registration і quiz -- LocalizedBlueprint, тож реальний шлях там `/ru/quiz/5`.
Російсько- й англомовний учасник бачив поп-ап поверх питань тесту, а в кабінеті
-- поп-ап разом із власним банером і самою анкетою.

Тому кожен виняток перевіряємо в трьох мовних варіантах: якщо хтось знову
звірятиметься з префіксом шляху, впаде саме ru/en.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.user import User

MARKER = 'id="certdata-reminder"'


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


@pytest.fixture
def registered_user(app):
    """Користувач із активною реєстрацією і НЕзаповненою анкетою."""
    user = User.create_with_password(
        f'cd-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Іван', last_name='Тестовий', email_confirmed=True)
    db.session.flush()

    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=f'cd-{uuid4().hex[:6]}',
                    is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        start_date=datetime.now(timezone.utc) - timedelta(days=1))
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='confirmed',
        payment_status='paid')
    db.session.add(reg)
    db.session.flush()
    return user, reg


# ---- де поп-ап потрібен ------------------------------------------------------

@pytest.mark.parametrize('path', ['/', '/ru/', '/en/'])
def test_popup_shows_on_public_pages(client, registered_user, path):
    user, _reg = registered_user
    _login(client, user)
    resp = client.get(path)
    assert resp.status_code == 200, path
    assert MARKER in resp.get_data(as_text=True), path


def test_no_popup_for_anonymous(client, registered_user):
    assert MARKER not in client.get('/').get_data(as_text=True)


def test_no_popup_when_profile_is_complete(client, registered_user):
    user, _reg = registered_user
    prof = MedicalProfile(
        user_id=user.id, participant_type='doctor', middle_name='Іванович',
        birth_date=datetime(1985, 3, 12).date(), education='2010, НМУ',
        workplace='Клініка', position='лікар', specializations=['therapy'])
    db.session.add(prof)
    user.medical_profile = prof
    db.session.flush()
    _login(client, user)
    assert MARKER not in client.get('/').get_data(as_text=True)


# ---- де поп-ап -- шум --------------------------------------------------------

@pytest.mark.parametrize('prefix', ['', '/ru', '/en'])
def test_muted_in_cabinet(client, registered_user, prefix):
    """У кабінеті вже є власний банер і сама анкета."""
    user, _reg = registered_user
    _login(client, user)
    resp = client.get(f'{prefix}/auth/account')
    assert resp.status_code == 200, prefix
    assert MARKER not in resp.get_data(as_text=True), prefix


@pytest.mark.parametrize('prefix', ['', '/ru', '/en'])
def test_muted_on_quiz_pages(client, registered_user, prefix):
    """Поверх питань тесту поп-ап -- чистий шум: гейт сам каже, чого бракує."""
    user, reg = registered_user
    _login(client, user)
    resp = client.get(f'{prefix}/quiz/{reg.id}')
    assert resp.status_code == 200, prefix
    assert MARKER not in resp.get_data(as_text=True), prefix


@pytest.mark.parametrize('prefix', ['', '/ru', '/en'])
def test_muted_on_certificate_data_form(client, registered_user, prefix):
    """Поп-ап, що пропонує відкрити форму, поверх самої форми."""
    user, _reg = registered_user
    _login(client, user)
    resp = client.get(f'{prefix}/auth/account/certificate-data')
    assert resp.status_code == 200, prefix
    assert MARKER not in resp.get_data(as_text=True), prefix


def test_admin_is_not_touched(client, registered_user):
    """В адмінці поп-ап не рендериться, і контекст-процесор туди не ходить."""
    user, _reg = registered_user
    grant_role(user, 'super_admin')
    db.session.flush()
    _login(client, user)
    resp = client.get('/admin/')
    assert MARKER not in resp.get_data(as_text=True)
