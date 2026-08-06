"""Промокод у публічному чекауті: знижка, 100%, помилки, AJAX-перевірка.

Тут перевіряється саме HTTP-шар (валідація до створення користувача,
відкат при вичерпаному коді, JSON для promo-code.js) -- математика знижок
живе у tests/test_services/test_promo_service.py.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.promo_code import PromoCode
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import promo_service


@pytest.fixture(autouse=True)
def _no_rate_limit(app):
    from app.extensions import limiter
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def _no_recaptcha(monkeypatch):
    monkeypatch.setattr('app.registration.routes.verify_recaptcha',
                        lambda action=None: True)


def _instance(price=1000):
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=f'p-{uuid4().hex[:6]}',
                    is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='online',
        price=price, start_date=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(inst)
    db.session.commit()
    return inst


def _promo(code, **kwargs):
    """Створити промокод з унікальним суфіксом.

    Роути комітять, тож рядки переживають per-test rollback -- без
    суфікса другий прогін впирався б у UNIQUE code_norm (те саме рішення,
    що й у тестах реферальної програми).
    """
    kwargs.setdefault('discount_type', 'percent')
    kwargs.setdefault('discount_value', Decimal('50'))
    code = f'{code}-{uuid4().hex[:6]}'
    promo = PromoCode(code=code, code_norm=promo_service.normalize_code(code),
                      **kwargs)
    db.session.add(promo)
    db.session.commit()
    return promo


def _url(inst):
    return f'/registration/instance/{inst.id}/register'


def _payload(**over):
    data = {
        'last_name': 'Промокодний',
        'first_name': 'Тест',
        'email': f'promo-{uuid4().hex[:6]}@test.com',
        'phone': '+380501112233',
        'consent_data': 'y',
    }
    data.update(over)
    return data


# --- форма ------------------------------------------------------------------

def test_promo_field_rendered_for_paid_event(client):
    html = client.get(_url(_instance())).get_data(as_text=True)
    assert 'name="promo_code"' in html
    assert 'data-promo-apply' in html


def test_promo_field_hidden_for_free_event(client):
    html = client.get(_url(_instance(price=0))).get_data(as_text=True)
    assert 'data-promo-apply' not in html


# --- покупка ----------------------------------------------------------------

def test_percent_discount_applied(client):
    inst = _instance(price=1000)
    promo = _promo('Дмитро', discount_value=Decimal('50'))

    # Регістр не має значення -- код шукається за нормалізованою формою.
    resp = client.post(_url(inst), data=_payload(promo_code=promo.code.lower()))
    assert resp.status_code == 302

    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.payment_amount == Decimal('500.00')
    assert reg.discount_amount == Decimal('500.00')
    assert reg.payment_status == 'unpaid'


def test_full_discount_makes_registration_free(client):
    inst = _instance(price=1000)
    promo = _promo('vip100', discount_value=Decimal('100'))

    client.post(_url(inst), data=_payload(promo_code=promo.code))

    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.payment_amount == Decimal('0.00')
    assert reg.status == 'confirmed'
    assert reg.payment_status == 'paid'


def test_fixed_amount_discount(client):
    inst = _instance(price=1000)
    promo = _promo('minus300', discount_type='amount',
                   discount_value=Decimal('300'))

    client.post(_url(inst), data=_payload(promo_code=promo.code))

    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.payment_amount == Decimal('700.00')


def test_unknown_code_blocks_registration(client):
    inst = _instance()
    resp = client.post(_url(inst), data=_payload(promo_code='нема-такого'))

    assert resp.status_code == 200            # форма з помилкою
    assert EventRegistration.query.filter_by(instance_id=inst.id).count() == 0
    # Користувача теж не створили: код перевіряється до resolve_user.
    assert User.query.filter_by(email='нема-такого').count() == 0


def test_exhausted_code_blocks_registration(client):
    inst = _instance()
    promo = _promo('spent', max_uses=1, used_count=1)

    resp = client.post(_url(inst), data=_payload(promo_code=promo.code))
    assert resp.status_code == 200
    assert EventRegistration.query.filter_by(instance_id=inst.id).count() == 0


def test_code_scoped_to_other_course_rejected(client):
    inst = _instance()
    other = _instance()
    promo = _promo('elsewhere', course_id=other.course_id)

    resp = client.post(_url(inst), data=_payload(promo_code=promo.code))
    assert resp.status_code == 200
    assert EventRegistration.query.filter_by(instance_id=inst.id).count() == 0


def test_max_uses_two_buyers(client):
    """B2B-кейс: фарма отримала код на 2 місця -- третій вже не пройде."""
    inst = _instance(price=1000)
    promo = _promo('pharma2', discount_value=Decimal('100'), max_uses=2)
    code = promo.code

    # Кожен _payload() -- новий email, тобто новий учасник.
    assert client.post(_url(inst), data=_payload(promo_code=code)).status_code == 302
    assert client.post(_url(inst), data=_payload(promo_code=code)).status_code == 302
    third = client.post(_url(inst), data=_payload(promo_code=code))
    assert third.status_code == 200

    promo = db.session.get(PromoCode, promo.id)
    assert promo.used_count == 2
    assert promo.is_exhausted is True


def test_registration_without_promo_is_unaffected(client):
    inst = _instance(price=1000)
    client.post(_url(inst), data=_payload())

    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.payment_amount == Decimal('1000.00')
    assert reg.promo_code_id is None
    assert reg.discount_amount is None


# --- AJAX-перевірка ---------------------------------------------------------

def _check_url(inst):
    return f'/registration/instance/{inst.id}/promo-check'


def test_promo_check_returns_discount(client):
    inst = _instance(price=1000)
    promo = _promo('check-me', discount_value=Decimal('25'))

    resp = client.post(_check_url(inst), data={'code': promo.code.upper()})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['ok'] is True
    assert payload['discount'] == 250
    assert payload['final'] == 750
    assert payload['is_free'] is False


def test_promo_check_reports_error_without_consuming(client):
    inst = _instance(price=1000)
    promo = _promo('look-only', max_uses=1)

    ok = client.post(_check_url(inst), data={'code': promo.code}).get_json()
    assert ok['ok'] is True
    # Перегляд не витрачає ліміт -- інакше друга вкладка "з'їла" б код.
    assert db.session.get(PromoCode, promo.id).used_count == 0

    bad = client.post(_check_url(inst), data={'code': 'no-such-code'}).get_json()
    assert bad['ok'] is False
    assert bad['message']


def test_promo_check_empty_code(client):
    resp = client.post(_check_url(_instance()), data={'code': '  '})
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False


def test_promo_check_404_for_inactive_course(client):
    """Та сама умова, що й на самій реєстрації: чернетка курсу не
    відповідає навіть на перевірку коду."""
    inst = _instance()
    inst.course.is_active = False
    db.session.commit()
    _promo('hidden')

    assert client.post(_check_url(inst), data={'code': 'hidden'}).status_code == 404


def test_promo_check_ignores_broken_tariff_id(client):
    """Сміття в tariff_id не має ламати перевірку -- рахуємо від ціни події."""
    inst = _instance(price=1000)
    promo = _promo('robust', discount_value=Decimal('10'))

    payload = client.post(_check_url(inst),
                          data={'code': promo.code, 'tariff_id': 'abc'}).get_json()
    assert payload['ok'] is True
    assert payload['final'] == 900
