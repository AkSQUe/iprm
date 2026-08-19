"""Шлях заявки на повернення: кабінет -> черга адміна -> повернення.

Найцінніше тут -- перевірка, що сума із заявки доживає до форми повернення
незміненою (§4.2), і що успішне повернення закриває заявку. Це саме ті два
місця, де зв'язка може мовчки розпастись: обидва боки працюватимуть, а
учасник отримає не ту суму або лишиться з «вічно відкритою» заявкою.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from tests import refund_fixtures

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.refund_request import RefundRequest
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import refund_requests


def _uid():
    return uuid4().hex[:6]


@pytest.fixture(autouse=True)
def clean(app):
    """Прибрати за собою закомічене: сервіс комітить, а БД спільна."""
    yield
    refund_fixtures.purge('rrf-', 'rrf-')


@pytest.fixture(autouse=True)
def quiet_mail(monkeypatch):
    from app.services.email_service import EmailService
    for name in ('send_refund_request_received',
                 'send_refund_request_notification',
                 'send_refund_request_declined',
                 'send_refund_notification'):
        monkeypatch.setattr(EmailService, name, staticmethod(lambda *a, **k: None))


def _user(admin=False):
    item = User.create_with_password(
        f'rrf-{_uid()}@test.com', 'password123',
        first_name='Тарас', last_name='Бойко',
        is_admin=admin, email_confirmed=True,
    )
    db.session.flush()
    return item


@pytest.fixture
def buyer(app):
    return _user()


@pytest.fixture
def admin(app):
    return _user(admin=True)


@pytest.fixture
def paid_reg(app, buyer):
    course = Course(title='Курс', slug=f'rrf-{_uid()}', is_active=False)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(course_id=course.id, status='published', price=1000,
                              start_date=utcnow() + timedelta(days=30))
    db.session.add(instance)
    db.session.flush()
    item = EventRegistration(
        user_id=buyer.id, instance_id=instance.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status='confirmed', payment_status='paid',
        payment_amount=Decimal('1000'), paid_at=utcnow(),
    )
    db.session.add(item)
    db.session.commit()
    return item


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def _liqpay():
    service = MagicMock()
    service.create_refund_request.return_value = {'status': 'reversed'}
    service.is_configured = True
    return service


# ------------------------------- кабінет -------------------------------

def test_cabinet_form_shows_the_amount_before_submitting(client, buyer, paid_reg):
    _login(client, buyer)

    response = client.get(f'/auth/account/refund/registration/{paid_reg.id}')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    # Захід через 30 днів -- повна сума, і людина бачить її ДО заповнення.
    assert '1000' in body


def test_submitting_creates_the_request(client, buyer, paid_reg):
    _login(client, buyer)

    response = client.post(
        f'/auth/account/refund/registration/{paid_reg.id}',
        data={'reason': 'Змінився графік чергувань'},
    )

    assert response.status_code == 302
    item = RefundRequest.query.filter_by(registration_id=paid_reg.id).one()
    assert item.status == 'new'
    assert item.reason == 'Змінився графік чергувань'
    assert item.quoted_amount == Decimal('1000.00')


def test_reason_is_required(client, buyer, paid_reg):
    _login(client, buyer)

    response = client.post(
        f'/auth/account/refund/registration/{paid_reg.id}', data={'reason': ' '})

    # Редирект назад на форму, а не рендер на місці: збій запису відкочує
    # сесію, і сторінка з протухлих об'єктів впала б 500-ю.
    assert response.status_code == 302
    assert 'refund/registration' in response.headers['Location']
    assert RefundRequest.query.filter_by(registration_id=paid_reg.id).count() == 0


def test_someone_elses_order_is_not_reachable(client, app, paid_reg):
    stranger = _user()
    db.session.commit()
    _login(client, stranger)

    response = client.get(f'/auth/account/refund/registration/{paid_reg.id}')

    assert response.status_code == 404


def test_second_request_is_refused(client, buyer, paid_reg):
    _login(client, buyer)
    refund_requests.create(paid_reg, buyer, reason='Перша')

    response = client.get(f'/auth/account/refund/registration/{paid_reg.id}')

    assert response.status_code == 302
    assert RefundRequest.query.filter_by(registration_id=paid_reg.id).count() == 1


# ---------------------------- черга адміна ----------------------------

def test_queue_lists_the_request(client, admin, buyer, paid_reg):
    refund_requests.create(paid_reg, buyer, reason='Змінився графік')
    _login(client, admin)

    response = client.get('/admin/refund-requests')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'REG-{paid_reg.id}' in body
    assert 'Змінився графік' in body


def test_rejection_requires_an_explanation(client, admin, buyer, paid_reg):
    item, _ = refund_requests.create(paid_reg, buyer, reason='Причина')
    _login(client, admin)

    response = client.post(f'/admin/refund-requests/{item.id}/reject',
                           data={'decision_note': '   '})

    assert response.status_code == 302
    db.session.refresh(item)
    assert item.status == 'new'


def test_rejection_records_the_note(client, admin, buyer, paid_reg):
    item, _ = refund_requests.create(paid_reg, buyer, reason='Причина')
    _login(client, admin)

    client.post(f'/admin/refund-requests/{item.id}/reject',
                data={'decision_note': 'Захід уже відбувся, п. 4.3'})

    db.session.refresh(item)
    assert item.status == 'rejected'
    assert 'п. 4.3' in item.decision_note


def test_queue_requires_admin(client, buyer):
    _login(client, buyer)
    assert client.get('/admin/refund-requests').status_code in (302, 403, 404)


# ------------------------- зв'язка із поверненням -------------------------

def test_refund_page_uses_the_amount_from_the_request(
        client, admin, buyer, paid_reg):
    """§4.2 доживає до форми: сума береться зі знімка заявки, не з «зараз»."""
    item, _ = refund_requests.create(paid_reg, buyer, reason='Причина')
    # Заявка пролежала в черзі, захід наблизився -- жива політика дала б 25%.
    paid_reg.instance.start_date = utcnow() + timedelta(days=1)
    db.session.commit()
    _login(client, admin)

    response = client.get(
        f'/admin/refunds/registration/{paid_reg.id}?request={item.id}')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="1000.00"' in body
    assert 'Заявка учасника' in body


def test_successful_refund_closes_the_request(client, admin, buyer, paid_reg):
    item, _ = refund_requests.create(paid_reg, buyer, reason='Причина')
    _login(client, admin)

    with patch('app.admin.routes_refunds.get_liqpay_service',
               return_value=_liqpay()):
        response = client.post(
            f'/admin/refunds/registration/{paid_reg.id}?request={item.id}',
            data={'amount': '1000', 'reason': 'За заявкою'},
        )

    assert response.status_code == 302
    db.session.refresh(item)
    assert item.status == 'approved'
    assert item.decided_by_id == admin.id


def test_request_id_from_another_order_is_ignored(client, admin, buyer, paid_reg):
    """Підмінений ?request= не має закривати чужу заявку."""
    # Друге ПРОВЕДЕННЯ, а не друга реєстрація на те саме: пара
    # (user, instance) унікальна.
    other_instance = CourseInstance(
        course_id=paid_reg.instance.course_id, status='published', price=500,
        start_date=utcnow() + timedelta(days=20),
    )
    db.session.add(other_instance)
    db.session.flush()
    other_reg = EventRegistration(
        user_id=buyer.id, instance_id=other_instance.id,
        phone='+380000000001', specialty='Лікар', workplace='Клініка',
        status='confirmed', payment_status='paid',
        payment_amount=Decimal('500'), paid_at=utcnow(),
    )
    db.session.add(other_reg)
    db.session.commit()
    foreign, _ = refund_requests.create(other_reg, buyer, reason='Чужа заявка')
    _login(client, admin)

    with patch('app.admin.routes_refunds.get_liqpay_service',
               return_value=_liqpay()):
        client.post(
            f'/admin/refunds/registration/{paid_reg.id}?request={foreign.id}',
            data={'amount': '100'},
        )

    db.session.refresh(foreign)
    assert foreign.status == 'new'


# ------------------------------ розширення ------------------------------

def test_cabinet_shows_the_rejection_and_its_reason(client, buyer, paid_reg):
    """Відмова має бути видимою в кабінеті, а не лише в листі."""
    item, _ = refund_requests.create(paid_reg, buyer, reason='Причина')
    refund_requests.reject(item, buyer, 'Захід уже відбувся, п. 4.3')
    _login(client, buyer)

    body = client.get('/auth/account').get_data(as_text=True)

    assert 'відхилено' in body
    assert 'п. 4.3' in body


def test_cabinet_hides_the_button_while_a_request_is_open(client, buyer, paid_reg):
    refund_requests.create(paid_reg, buyer, reason='Причина')
    _login(client, buyer)

    body = client.get('/auth/account').get_data(as_text=True)

    assert 'на розгляді' in body
    assert f'/refund/registration/{paid_reg.id}' not in body


def test_cabinet_offers_a_new_request_after_a_rejection(client, buyer, paid_reg):
    """Відмова -- не вирок: обставини можуть змінитись."""
    item, _ = refund_requests.create(paid_reg, buyer, reason='Причина')
    refund_requests.reject(item, buyer, 'Недостатньо підстав')
    _login(client, buyer)

    body = client.get('/auth/account').get_data(as_text=True)

    assert f'/refund/registration/{paid_reg.id}' in body


def test_queue_exports_to_xlsx(client, admin, buyer, paid_reg):
    refund_requests.create(paid_reg, buyer, reason='Змінився графік')
    _login(client, admin)

    response = client.get('/admin/refund-requests/export')

    assert response.status_code == 200
    assert 'spreadsheet' in response.headers['Content-Type']
    assert response.data[:2] == b'PK'  # xlsx -- це zip


def test_sidebar_counts_only_open_requests(client, admin, buyer, paid_reg):
    item, _ = refund_requests.create(paid_reg, buyer, reason='Причина')
    _login(client, admin)

    with_open = client.get('/admin/refund-requests').get_data(as_text=True)
    refund_requests.reject(item, admin, 'Ні')
    after = client.get('/admin/refund-requests').get_data(as_text=True)

    # Лічильник у сайдбарі: пункт меню є завжди, число -- лише поки є нові.
    assert 'Заявки на повернення' in with_open
    assert 'badge--danger' in with_open
    assert 'badge--danger' not in after
