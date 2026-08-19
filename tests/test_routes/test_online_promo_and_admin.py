"""Промокоди на онлайн-курси і ручне підтвердження оплати.

Це грошовий шлях, тож тут стережеться не рендер, а правила: код на захід не
діє на онлайн-курс, ліміт «на одну людину» бачить обидва типи замовлень,
повернення коштів звільняє використання, а ручне «оплачено» відкриває
доступ так само, як це робить callback LiqPay.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.promo_code import PromoCode, PromoRedemption
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import promo_service


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """Лімітер рахує запити на весь набір, а не на тест.

    Без цього десяток перевірок чекауту вичерпує «20 на годину», і решта
    падає з 429 -- на порожньому місці, бо ліміт тут не предмет перевірки.
    Той самий підхід, що в test_checkout_hardening.
    """
    from app.extensions import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def clean(app):
    """Чисті таблиці промокодів і замовлень перед кожним тестом.

    PromoCode прибираємо теж, і саме через SQLite: після видалення рядків
    він перевикористовує ідентифікатори, тож нове замовлення отримує id
    попереднього -- а виданий за те замовлення код-подяка лишався б
    прив'язаним і повертався замість None.
    """
    def _wipe():
        PromoRedemption.query.delete()
        PromoCode.query.delete()
        OnlineEnrollment.query.delete()
        OnlineCourse.query.delete()
        db.session.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def buyer(app):
    user = User.create_with_password(
        f'pb-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Ольга', last_name='Коваль', email_confirmed=True,
    )
    db.session.commit()
    return user


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'pa-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='А', last_name='Адмін', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    return user


@pytest.fixture
def course(app):
    item = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Плазмотерапія',
        slug=f'pr-{uuid4().hex[:8]}',
        remote_price=Decimal('4000'),
        is_published=True,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _promo(**kwargs):
    code = f'ONL{uuid4().hex[:6].upper()}'
    kwargs.setdefault('discount_type', 'percent')
    kwargs.setdefault('discount_value', Decimal('25'))
    promo = PromoCode(code=code, code_norm=promo_service.normalize_code(code),
                      **kwargs)
    db.session.add(promo)
    db.session.commit()
    return promo


def _flash_messages(response):
    """Тексти flash-повідомлень зі сторінки.

    Вони віддаються JSON-ом у <script id="iprm-flash-data">, тобто
    кирилиця в HTML лежить екранованою (\\uXXXX) -- шукати підрядок у
    сирому тілі марно.
    """
    import json
    import re

    match = re.search(r'id="iprm-flash-data"[^>]*>(.*?)</script>',
                      response.get_data(as_text=True), re.S)
    if not match:
        return []
    return [item['message'] for item in json.loads(match.group(1))]


def _login(client, user):
    """Увійти як `user`, скинувши попередню сесію.

    Саме `clear()`: у тестах, де клієнт спершу ходить покупцем, а потім
    адміном, підміна одного лише `_user_id` лишає відбиток попередньої
    сесії, і Flask-Login скидає її цілком -- запит іде анонімним, а тест
    падає на незрозумілому «сторінка вимагає входу».
    """
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def _enrollment(buyer, course, **kwargs):
    kwargs.setdefault('payment_amount', course.effective_price)
    item = OnlineEnrollment(user_id=buyer.id, online_course_id=course.id, **kwargs)
    db.session.add(item)
    db.session.commit()
    return item


# ----------------------------- застосування -----------------------------

class TestApply:
    def test_discount_lands_on_the_order(self, app, buyer, course):
        promo = _promo()
        enrollment = _enrollment(buyer, course)

        promo_service.apply_to_enrollment(promo, enrollment,
                                          course.effective_price)
        db.session.commit()

        assert enrollment.discount_amount == Decimal('1000')
        assert enrollment.payment_amount == Decimal('3000')
        assert enrollment.promo_code_id == promo.id

    def test_redemption_is_recorded_against_the_order(self, app, buyer, course):
        promo = _promo()
        enrollment = _enrollment(buyer, course)

        promo_service.apply_to_enrollment(promo, enrollment,
                                          course.effective_price)
        db.session.commit()

        redemption = PromoRedemption.query.filter_by(
            enrollment_id=enrollment.id).one()
        assert redemption.registration_id is None
        assert redemption.status == 'applied'
        assert redemption.original_amount == Decimal('4000')

    def test_counter_moves_once(self, app, buyer, course):
        promo = _promo()
        enrollment = _enrollment(buyer, course)

        promo_service.apply_to_enrollment(promo, enrollment, Decimal('4000'))
        promo_service.apply_to_enrollment(promo, enrollment, Decimal('4000'))
        db.session.commit()

        assert promo.used_count == 1
        assert PromoRedemption.query.filter_by(
            enrollment_id=enrollment.id, status='applied').count() == 1

    def test_replacing_a_code_voids_the_previous(self, app, buyer, course):
        first, second = _promo(), _promo()
        enrollment = _enrollment(buyer, course)

        promo_service.apply_to_enrollment(first, enrollment, Decimal('4000'))
        db.session.commit()
        promo_service.apply_to_enrollment(second, enrollment, Decimal('4000'))
        db.session.commit()

        assert enrollment.promo_code_id == second.id
        assert first.used_count == 0
        assert PromoRedemption.query.filter_by(
            enrollment_id=enrollment.id, status='applied').count() == 1

    def test_detach_returns_the_use(self, app, buyer, course):
        promo = _promo()
        enrollment = _enrollment(buyer, course)
        promo_service.apply_to_enrollment(promo, enrollment, Decimal('4000'))
        db.session.commit()

        promo_service.detach_from_enrollment(enrollment)
        db.session.commit()

        assert promo.used_count == 0
        assert enrollment.promo_code_id is None
        assert enrollment.discount_amount is None


# ----------------------------- область дії -----------------------------

class TestScope:
    def test_event_scoped_code_does_not_apply_online(self, app, buyer, course):
        """Код на конкретний захід не має давати знижку на онлайн-курс."""
        offline = Course(title='Захід', slug=f'ev-{uuid4().hex[:6]}',
                         is_active=False)
        db.session.add(offline)
        db.session.flush()
        instance = CourseInstance(course_id=offline.id, status='published',
                                  price=1000)
        db.session.add(instance)
        db.session.commit()

        promo = _promo(instance_id=instance.id)

        with pytest.raises(promo_service.PromoError):
            promo_service.validate_for_online(promo.code, amount=Decimal('4000'))

    def test_course_scoped_code_does_not_apply_online(self, app, buyer, course):
        offline = Course(title='Курс', slug=f'cs-{uuid4().hex[:6]}',
                         is_active=False)
        db.session.add(offline)
        db.session.commit()
        promo = _promo(course_id=offline.id)

        with pytest.raises(promo_service.PromoError):
            promo_service.validate_for_online(promo.code, amount=Decimal('4000'))

    def test_global_code_applies(self, app, course):
        promo = _promo()
        found, discount, final = promo_service.validate_for_online(
            promo.code, amount=Decimal('4000'))

        assert found.id == promo.id
        assert discount == Decimal('1000')
        assert final == Decimal('3000')


# ----------------------------- ліміт на людину -----------------------------

class TestUserLimit:
    def test_limit_counts_both_order_types(self, app, buyer, course):
        """Код із лімітом 1 не можна використати двічі -- по разу на кожен тип."""
        promo = _promo(per_user_limit=1)

        offline = Course(title='Захід', slug=f'lm-{uuid4().hex[:6]}',
                         is_active=False)
        db.session.add(offline)
        db.session.flush()
        instance = CourseInstance(course_id=offline.id, status='published',
                                  price=1000)
        db.session.add(instance)
        db.session.flush()
        reg = EventRegistration(
            user_id=buyer.id, instance_id=instance.id, phone='+380000000000',
            specialty='X', workplace='Y', payment_amount=Decimal('1000'),
        )
        db.session.add(reg)
        db.session.commit()

        promo_service.apply_to_registration(promo, reg, Decimal('1000'))
        db.session.commit()

        with pytest.raises(promo_service.PromoError):
            promo_service.assert_user_limit(promo, buyer.id)

    def test_same_order_does_not_block_itself(self, app, buyer, course):
        promo = _promo(per_user_limit=1)
        enrollment = _enrollment(buyer, course)
        promo_service.apply_to_enrollment(promo, enrollment, Decimal('4000'))
        db.session.commit()

        # Повторне збереження того самого замовлення не має падати.
        promo_service.assert_user_limit(promo, buyer.id,
                                        ignore_enrollment_id=enrollment.id)


# ----------------------------- чекаут -----------------------------

class TestCheckout:
    def test_code_is_applied_from_the_form(self, client, buyer, course):
        promo = _promo()
        _login(client, buyer)
        client.get(f'/online-courses/{course.slug}/checkout')

        client.post(f'/online-courses/{course.slug}/checkout',
                    data={'promo_code': promo.code}, follow_redirects=True)

        enrollment = OnlineEnrollment.query.filter_by(user_id=buyer.id).one()
        assert enrollment.payment_amount == Decimal('3000')

    def test_bad_code_shows_an_error_and_keeps_the_price(self, client, buyer,
                                                         course):
        _login(client, buyer)
        client.get(f'/online-courses/{course.slug}/checkout')

        # PRG: помилка приходить flash-повідомленням уже на GET.
        response = client.post(f'/online-courses/{course.slug}/checkout',
                               data={'promo_code': 'NOPE'},
                               follow_redirects=True)

        assert any('не знайдено' in m for m in _flash_messages(response))
        enrollment = OnlineEnrollment.query.filter_by(user_id=buyer.id).one()
        assert enrollment.payment_amount == Decimal('4000')

    def test_removing_the_code_restores_the_price(self, client, buyer, course):
        promo = _promo()
        _login(client, buyer)
        client.get(f'/online-courses/{course.slug}/checkout')
        client.post(f'/online-courses/{course.slug}/checkout',
                    data={'promo_code': promo.code})

        client.post(f'/online-courses/{course.slug}/checkout',
                    data={'remove_promo': '1'})

        enrollment = OnlineEnrollment.query.filter_by(user_id=buyer.id).one()
        assert enrollment.payment_amount == Decimal('4000')
        assert enrollment.promo_code_id is None

    def test_second_application_does_not_stack(self, client, buyer, course):
        """Знижка рахується від ціни курсу, а не від уже здешевленої суми."""
        promo = _promo()
        _login(client, buyer)
        client.get(f'/online-courses/{course.slug}/checkout')

        client.post(f'/online-courses/{course.slug}/checkout',
                    data={'promo_code': promo.code})
        client.post(f'/online-courses/{course.slug}/checkout',
                    data={'promo_code': promo.code})

        enrollment = OnlineEnrollment.query.filter_by(user_id=buyer.id).one()
        assert enrollment.payment_amount == Decimal('3000')


# ----------------------------- ручне підтвердження -----------------------------

class TestAdminOrders:
    def test_page_requires_admin(self, client, buyer):
        _login(client, buyer)
        assert client.get('/admin/online-orders').status_code in (302, 403, 404)

    def test_page_lists_orders(self, client, admin, buyer, course):
        _enrollment(buyer, course)
        _login(client, admin)

        body = client.get('/admin/online-orders').get_data(as_text=True)
        assert 'ONL-' in body
        assert 'Плазмотерапія' in body

    def test_manual_paid_opens_access(self, client, admin, buyer, course,
                                      monkeypatch):
        """Ручне «оплачено» має відкривати курс так само, як callback."""
        from app.services import sintegrum_access

        course.access_url = 'https://multimededu.sintegrum.com/register/abc'
        db.session.commit()
        enrollment = _enrollment(buyer, course)
        monkeypatch.setattr(
            'app.services.email_service.EmailService.send_online_access',
            staticmethod(lambda *a, **k: None))
        _login(client, admin)

        client.post(f'/admin/online-orders/{enrollment.id}/payment',
                    data={'payment_status': 'paid'}, follow_redirects=True)

        db.session.refresh(enrollment)
        assert enrollment.payment_status == 'paid'
        assert enrollment.provisioned_at is not None
        assert enrollment.access_token
        assert sintegrum_access  # модуль справді бере участь у шляху

    def test_refund_voids_the_promo(self, app, buyer, course, monkeypatch):
        """Повернення коштів звільняє використання коду, але лишає знімок.

        Перевіряється на рівні PaymentOps, а не через сторінку: правило
        живе саме там і однакове для callback LiqPay і для ручної зміни
        статусу в адмінці (вона викликає той самий метод).
        """
        from app.services.liqpay import get_liqpay_service
        from app.services.payment_ops import PaymentOps

        monkeypatch.setattr(
            'app.services.email_service.EmailService.send_online_access',
            staticmethod(lambda *a, **k: None))
        course.access_url = 'https://multimededu.sintegrum.com/register/abc'
        db.session.commit()

        promo = _promo()
        enrollment = _enrollment(buyer, course)
        promo_service.apply_to_enrollment(promo, enrollment, Decimal('4000'))
        db.session.commit()
        assert enrollment.payment_amount == Decimal('3000')

        ops = PaymentOps(get_liqpay_service())
        ok, _msg = ops.update_enrollment_status(enrollment, 'paid',
                                                source='manual')
        assert ok is True
        ops.update_enrollment_status(enrollment, 'refunded', source='manual')

        db.session.refresh(enrollment)
        db.session.refresh(promo)
        assert enrollment.payment_status == 'refunded'
        # Використання звільнено -- код можна видати комусь іншому...
        assert promo.used_count == 0
        # ...але знімок знижки лишається: людина платила саме стільки.
        assert enrollment.discount_amount == Decimal('1000')
        # ...і доступ забрано разом із поверненням.
        assert enrollment.access_token is None

    def test_unknown_status_is_rejected(self, client, admin, buyer, course):
        enrollment = _enrollment(buyer, course)
        _login(client, admin)

        client.post(f'/admin/online-orders/{enrollment.id}/payment',
                    data={'payment_status': 'whatever'}, follow_redirects=True)

        db.session.refresh(enrollment)
        assert enrollment.payment_status == 'unpaid'

# ----------------------------- зафіксована сума -----------------------------

class TestFrozenAmount:
    """Сума замовлення не має «плавати» слідом за ціною курсу.

    Ціна змінюється і з адмінки, і черговою синхронізацією з Sintegrum, а
    замовлення вже оформлене -- людина бачила іншу цифру.
    """

    def test_price_change_does_not_leak_through_promo(self, client, buyer,
                                                      course):
        promo = _promo()
        _login(client, buyer)
        client.get(f'/online-courses/{course.slug}/checkout')

        # Курс подорожчав уже після оформлення замовлення.
        course.price = Decimal('9000')
        db.session.commit()

        client.post(f'/online-courses/{course.slug}/checkout',
                    data={'promo_code': promo.code}, follow_redirects=True)

        enrollment = OnlineEnrollment.query.filter_by(user_id=buyer.id).one()
        # 25% від зафіксованих 4000, а не від нових 9000.
        assert enrollment.payment_amount == Decimal('3000')

    def test_price_change_does_not_leak_through_removal(self, client, buyer,
                                                        course):
        promo = _promo()
        _login(client, buyer)
        client.get(f'/online-courses/{course.slug}/checkout')
        client.post(f'/online-courses/{course.slug}/checkout',
                    data={'promo_code': promo.code}, follow_redirects=True)

        course.price = Decimal('9000')
        db.session.commit()

        client.post(f'/online-courses/{course.slug}/checkout',
                    data={'remove_promo': '1'}, follow_redirects=True)

        enrollment = OnlineEnrollment.query.filter_by(user_id=buyer.id).one()
        assert enrollment.payment_amount == Decimal('4000')


class TestPerUserLimitOnTheSameOrder:
    def test_reapplying_the_same_code_is_allowed(self, client, buyer, course):
        """Ліміт «одне застосування на людину» не має блокувати те саме
        замовлення: людина просто ще раз натиснула «Застосувати»."""
        promo = _promo(per_user_limit=1)
        _login(client, buyer)
        client.get(f'/online-courses/{course.slug}/checkout')

        client.post(f'/online-courses/{course.slug}/checkout',
                    data={'promo_code': promo.code}, follow_redirects=True)
        response = client.post(f'/online-courses/{course.slug}/checkout',
                               data={'promo_code': promo.code},
                               follow_redirects=True)

        messages = _flash_messages(response)
        assert not any('вже використали' in m for m in messages), messages
        enrollment = OnlineEnrollment.query.filter_by(user_id=buyer.id).one()
        assert enrollment.payment_amount == Decimal('3000')


class TestFreeOrder:
    """Знижка 100% -- платити нічого, але доступ має відкритись."""

    def test_full_discount_completes_the_purchase(self, client, buyer, course,
                                                  monkeypatch):
        monkeypatch.setattr(
            'app.services.email_service.EmailService.send_online_access',
            staticmethod(lambda *a, **k: None))
        course.access_url = 'https://multimededu.sintegrum.com/register/abc'
        db.session.commit()

        promo = _promo(discount_value=Decimal('100'))
        _login(client, buyer)
        client.get(f'/online-courses/{course.slug}/checkout')
        client.post(f'/online-courses/{course.slug}/checkout',
                    data={'promo_code': promo.code}, follow_redirects=True)

        # PRG після застосування коду веде назад на чекаут, а той бачить
        # нульову суму й одразу закриває замовлення -- без форми LiqPay.
        enrollment = OnlineEnrollment.query.filter_by(user_id=buyer.id).one()
        assert enrollment.payment_amount == Decimal('0')
        assert enrollment.payment_status == 'paid'
        assert enrollment.access_token
        assert enrollment.provisioned_at is not None


class TestAmountCheck:
    def test_zero_expected_amount_is_still_verified(self):
        """Замовлення на нуль не має мовчки приймати будь-який платіж."""
        from app.services.payment_ops import check_amount

        assert check_amount(Decimal('0'), 500, 'ONL-1') == 'amount mismatch'
        assert check_amount(Decimal('0'), 0, 'ONL-1') is None
        # Сума не зафіксована -- звіряти нема з чим.
        assert check_amount(None, 500, 'ONL-1') is None


class TestRefundStaysOutOfTheTransaction:
    def test_remote_revoke_runs_after_commit(self, app, buyer, course,
                                             monkeypatch):
        """Мережевий виклик до Sintegrum не має жити всередині транзакції.

        Перевіряємо за наслідком: на момент звернення до партнера статус уже
        збережений, тобто коміт відбувся раніше.
        """
        from app.services import sintegrum_access
        from app.services.liqpay import get_liqpay_service
        from app.services.payment_ops import PaymentOps

        monkeypatch.setattr(
            'app.services.email_service.EmailService.send_online_access',
            staticmethod(lambda *a, **k: None))
        course.access_url = 'https://multimededu.sintegrum.com/register/abc'
        db.session.commit()

        enrollment = _enrollment(buyer, course)
        ops = PaymentOps(get_liqpay_service())
        ops.update_enrollment_status(enrollment, 'paid',
                                     amount=enrollment.payment_amount,
                                     source='manual')

        seen = {}

        def _remote(item):
            seen['status_at_call'] = db.session.get(
                OnlineEnrollment, item.id).payment_status
            return True

        monkeypatch.setattr(sintegrum_access, 'revoke_remote', _remote)
        ops.update_enrollment_status(enrollment, 'refunded', source='manual')

        assert seen['status_at_call'] == 'refunded'
        db.session.refresh(enrollment)
        assert enrollment.access_token is None

# ----------------------------- повернення коштів через LiqPay -----------------------------

class TestRefundThroughLiqpay:
    """Кнопка «Повернути кошти» справді рухає гроші, а не лише статус."""

    @staticmethod
    def _ops(refund_result):
        from unittest.mock import MagicMock
        from app.services.payment_ops import PaymentOps

        service = MagicMock()
        service.create_refund_request.return_value = refund_result
        return PaymentOps(service), service

    def _paid(self, buyer, course, monkeypatch):
        from app.services.liqpay import get_liqpay_service
        from app.services.payment_ops import PaymentOps

        monkeypatch.setattr(
            'app.services.email_service.EmailService.send_online_access',
            staticmethod(lambda *a, **k: None))
        course.access_url = 'https://multimededu.sintegrum.com/register/abc'
        db.session.commit()
        enrollment = _enrollment(buyer, course)
        PaymentOps(get_liqpay_service()).update_enrollment_status(
            enrollment, 'paid', amount=enrollment.payment_amount,
            source='manual')
        return enrollment

    def test_successful_refund_closes_access(self, app, buyer, course, admin,
                                             monkeypatch):
        enrollment = self._paid(buyer, course, monkeypatch)
        ops, service = self._ops({'status': 'reversed'})

        # force=True: оплата вже видала доступ, а п. 5.1 забороняє
        # повертати кошти за цифровий продукт після цього. Тут перевіряємо
        # саму механіку повернення, тож виняток ставимо явно (заборону
        # стереже tests/test_services/test_refunds.py).
        ok, message = ops.initiate_enrollment_refund(
            enrollment, admin, force=True)

        assert ok is True
        assert '4000' in message
        service.create_refund_request.assert_called_once()
        db.session.refresh(enrollment)
        assert enrollment.payment_status == 'refunded'
        assert enrollment.access_token is None

    def test_rejected_refund_leaves_the_order_paid(self, app, buyer, course,
                                                  admin, monkeypatch):
        """LiqPay відмовив -- статус чіпати не можна: гроші не повернуто."""
        enrollment = self._paid(buyer, course, monkeypatch)
        ops, _service = self._ops({'status': 'error',
                                   'err_description': 'no funds'})

        ok, message = ops.initiate_enrollment_refund(
            enrollment, admin, force=True)

        assert ok is False
        assert 'no funds' in message
        db.session.refresh(enrollment)
        assert enrollment.payment_status == 'paid'
        assert enrollment.access_token

    def test_unpaid_order_cannot_be_refunded(self, app, buyer, course, admin):
        enrollment = _enrollment(buyer, course)
        ops, service = self._ops({'status': 'reversed'})

        ok, _message = ops.initiate_enrollment_refund(enrollment, admin)

        assert ok is False
        service.create_refund_request.assert_not_called()

    def test_free_order_needs_no_liqpay(self, app, buyer, course, monkeypatch,
                                        admin):
        """Замовлення на нуль LiqPay не знає -- закриваємо лише доступ."""
        monkeypatch.setattr(
            'app.services.email_service.EmailService.send_online_access',
            staticmethod(lambda *a, **k: None))
        course.access_url = 'https://multimededu.sintegrum.com/register/abc'
        db.session.commit()

        enrollment = _enrollment(buyer, course, payment_amount=Decimal('0'))
        ops, service = self._ops(None)
        ops.update_enrollment_status(enrollment, 'paid', amount=Decimal('0'),
                                     source='manual')

        ok, _message = ops.initiate_enrollment_refund(enrollment, admin)

        assert ok is True
        service.create_refund_request.assert_not_called()
        db.session.refresh(enrollment)
        assert enrollment.payment_status == 'refunded'


# ----------------------------- рахунок на оплату -----------------------------

class TestInvoice:
    def test_invoice_is_generated_for_the_buyer(self, client, buyer, course):
        _login(client, buyer)
        client.get(f'/online-courses/{course.slug}/checkout')
        enrollment = OnlineEnrollment.query.filter_by(user_id=buyer.id).one()

        response = client.get(f'/online-courses/orders/{enrollment.id}/invoice.pdf')

        assert response.status_code == 200
        assert response.mimetype == 'application/pdf'
        assert response.data[:4] == b'%PDF'

    def test_invoice_names_the_course(self, app, buyer, course):
        from app.services.invoice_service import _invoice_context

        enrollment = _enrollment(buyer, course)
        ctx = _invoice_context(enrollment)

        assert 'Онлайн-курс' in ctx['item_name']
        assert course.effective_title in ctx['item_name']
        assert ctx['amount'] == Decimal('4000')

    def test_someone_elses_order_is_404(self, client, buyer, course, admin):
        enrollment = _enrollment(buyer, course)
        _login(client, admin)

        assert client.get(
            f'/online-courses/orders/{enrollment.id}/invoice.pdf'
        ).status_code == 404

    def test_paid_order_has_no_invoice(self, client, buyer, course):
        enrollment = _enrollment(buyer, course, payment_status='paid',
                                 status='active')
        _login(client, buyer)

        response = client.get(
            f'/online-courses/orders/{enrollment.id}/invoice.pdf')
        assert response.status_code == 302


# ----------------------------- промокод-подяка -----------------------------

class TestThankyouPromo:
    def _enable(self):
        from app.models.site_settings import SiteSettings

        settings = SiteSettings.get()
        settings.thankyou_promo_enabled = True
        settings.thankyou_promo_percent = 10
        settings.thankyou_promo_days = 30
        db.session.commit()
        return settings

    def test_code_is_issued_and_sent_with_access(self, app, buyer, course,
                                                 monkeypatch):
        from app.services import sintegrum_access

        self._enable()
        course.access_url = 'https://multimededu.sintegrum.com/register/abc'
        db.session.commit()
        sent = {}
        monkeypatch.setattr(
            'app.services.email_service.EmailService.send_online_access',
            staticmethod(lambda item, url, promo=None: sent.update(promo=promo)))

        enrollment = _enrollment(buyer, course, payment_status='paid',
                                 status='active')
        sintegrum_access.provision_and_notify(enrollment)

        assert sent['promo'] is not None
        assert sent['promo'].discount_value == Decimal('10')
        assert sent['promo'].issued_for_enrollment_id == enrollment.id

    def test_issuing_is_idempotent(self, app, buyer, course):
        self._enable()
        enrollment = _enrollment(buyer, course)

        first = promo_service.issue_thankyou_code_for_enrollment(enrollment)
        db.session.commit()
        second = promo_service.issue_thankyou_code_for_enrollment(enrollment)

        assert first is not None
        assert second.id == first.id

    def test_disabled_mechanic_issues_nothing(self, app, buyer, course):
        from app.models.site_settings import SiteSettings

        settings = SiteSettings.get()
        settings.thankyou_promo_enabled = False
        db.session.commit()

        enrollment = _enrollment(buyer, course)
        assert promo_service.issue_thankyou_code_for_enrollment(enrollment) is None

    def test_registration_codes_still_work(self, app, buyer):
        """Узагальнення не мало зачепити наявну механіку для заходів."""
        from uuid import uuid4 as _uuid

        from app.models.course import Course as OfflineCourse
        from app.models.course_instance import CourseInstance
        from app.models.registration import EventRegistration

        self._enable()
        offline = OfflineCourse(title='Захід', slug=f'ty-{_uuid().hex[:6]}',
                                is_active=False)
        db.session.add(offline)
        db.session.flush()
        instance = CourseInstance(course_id=offline.id, status='published',
                                  price=1000)
        db.session.add(instance)
        db.session.flush()
        reg = EventRegistration(
            user_id=buyer.id, instance_id=instance.id, phone='+380000000000',
            specialty='X', workplace='Y', payment_amount=Decimal('1000'),
        )
        db.session.add(reg)
        db.session.commit()

        promo = promo_service.issue_thankyou_code(reg)

        assert promo is not None
        assert promo.issued_for_registration_id == reg.id
        assert promo.issued_for_enrollment_id is None


def test_orders_page_filters_by_access_state(client, admin, buyer, course):
    """Лічильник "зависло" тепер клікабельний -- фільтр за ним існує."""
    stuck = OnlineEnrollment(
        user_id=buyer.id, online_course_id=course.id,
        payment_amount=Decimal('4000'), payment_status='paid', status='active',
    )
    db.session.add(stuck)
    db.session.commit()

    _login(client, admin)
    body = client.get('/admin/online-orders?access=stuck').get_data(as_text=True)

    assert stuck.order_id in body
    assert 'без доступу' in body
