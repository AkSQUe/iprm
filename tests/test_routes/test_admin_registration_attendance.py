"""Маршрут підтвердження присутності: /admin/registrations/<id>/attendance.

Task 6 (розщеплення балів БПР за форматом участі) змінила тут найризикованіше
без жодного попереднього автотесту на цей роут: розбір користувацького вводу
перевели з `type=int` на `parse_points` (дробові числа, кома/крапка), а
верхню межу -- на `Decimal` замість `int`. Три гілки нижче стережуть саме це.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User


@pytest.fixture
def admin_client(app, client):
    user = User.create_with_password(
        f'attn-admin-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Адмін', last_name='Д', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    yield client
    # Прибираємо за собою: база живе через увесь прогін, зайві закомічені
    # користувачі зсувають пагіновані вибірки сусідніх тестів
    # (напр. tests/test_routes/test_api_v1_clients.py).
    db.session.delete(user)
    db.session.commit()


def _hybrid_registration(participation_format):
    """Гібридний захід: онлайн 7,50 / очно 9,00; реєстрація заданого формату."""
    course = Course(
        title='Гібрид БПР', slug=f'attn-{uuid4().hex[:8]}',
        is_active=True, event_type='course',
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, event_format='hybrid', status='completed',
        start_date=datetime.now(timezone.utc) - timedelta(days=1),
        cpd_points_online=Decimal('7.50'), cpd_points_offline=Decimal('9.00'),
    )
    db.session.add(inst)
    db.session.flush()
    user = User.create_with_password(
        f'attn-p-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Учасник', last_name='Тестовий', email_confirmed=True,
    )
    db.session.commit()
    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='confirmed',
        payment_status='paid', participation_format=participation_format,
    )
    db.session.add(reg)
    db.session.commit()
    return reg, user


def _cleanup(reg, user):
    # Той самий мотив, що й для admin_client: реєстрація й учасник комітяться
    # по-справжньому (роут усередині теж комітить), тож самі не відкотяться.
    db.session.delete(reg)
    db.session.delete(user)
    db.session.commit()


def test_blank_field_awards_the_points_due_to_this_person(admin_client):
    """Порожнє поле балів -- «нарахувати належне»: онлайновий учасник
    гібрида отримує СВОЇ 7,50, а не офлайнові 9,00 і не 0."""
    reg, user = _hybrid_registration('online')
    try:
        resp = admin_client.post(
            f'/admin/registrations/{reg.id}/attendance',
            data={'cpd_points': ''}, follow_redirects=True,
        )
        assert resp.status_code == 200
        db.session.refresh(reg)
        assert reg.cpd_points_awarded == Decimal('7.50')
        assert reg.attended is True
        assert reg.status == 'completed'
    finally:
        _cleanup(reg, user)


def test_non_numeric_value_is_rejected_without_crashing(admin_client):
    """Нечислове значення -- flash-помилка й редирект, а не 500; бали
    лишаються незмінними (None -- нічого ще не нараховано)."""
    reg, user = _hybrid_registration('offline')
    try:
        resp = admin_client.post(
            f'/admin/registrations/{reg.id}/attendance',
            data={'cpd_points': 'багато'}, follow_redirects=True,
        )
        assert resp.status_code == 200
        assert 'Некоректна кількість балів БПР' in resp.get_data(as_text=True)
        db.session.refresh(reg)
        assert reg.cpd_points_awarded is None
    finally:
        _cleanup(reg, user)


def test_value_over_the_cap_is_rejected(admin_client):
    """Понад межу (2x належного цій людині, або принаймні 100) --
    відхилено тим самим шляхом; арифметика межі (`base_cpd * 2`,
    `max(..., 100)`) на Decimal не падає з винятком."""
    reg, user = _hybrid_registration('offline')
    try:
        # due_cpd_points = 9.00 -> max_cpd = 18.00 -> межа = max(18.00, 100) = 100.
        resp = admin_client.post(
            f'/admin/registrations/{reg.id}/attendance',
            data={'cpd_points': '150'}, follow_redirects=True,
        )
        assert resp.status_code == 200
        assert 'Некоректна кількість балів БПР' in resp.get_data(as_text=True)
        db.session.refresh(reg)
        assert reg.cpd_points_awarded is None
    finally:
        _cleanup(reg, user)
