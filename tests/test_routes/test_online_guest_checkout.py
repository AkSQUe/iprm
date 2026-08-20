"""Гостьова покупка онлайн-курсу -- без створення акаунта наперед.

Перевіряється головне: людина без логіну доходить до оплати, її замовлення
не видно чужим, а наявний акаунт від такої покупки не страждає -- ані ПІБ,
ані паролем.
"""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.mixins import utcnow
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.user import User

ACCESS_URL = 'https://multimededu.sintegrum.com/register/secret-guest'


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """Ліміти рахуються на весь набір -- інакше половина тестів ловить 429."""
    from app.extensions import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def clean(app):
    """Сервіси комітять, тож рядки переживають відкат тестової транзакції."""
    OnlineEnrollment.query.delete()
    OnlineCourse.query.delete()
    db.session.commit()
    yield
    OnlineEnrollment.query.delete()
    OnlineCourse.query.delete()
    db.session.commit()


@pytest.fixture
def course(app):
    item = OnlineCourse(
        sintegrum_id=int(uuid4().int % 10_000_000),
        remote_name='Плазмотерапія в неврології',
        slug=f'gc-{uuid4().hex[:8]}',
        price=Decimal('4500'),
        access_url=ACCESS_URL,
        is_published=True,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _buyer_data(email=None, **over):
    data = {
        'last_name': 'Коваль',
        'first_name': 'Ольга',
        'email': email or f'guest-{uuid4().hex[:8]}@test.com',
        'phone': '+380671234567',
        'consent_data': 'y',
    }
    data.update(over)
    return data


def _buy(client, course, **over):
    """Пройти гостьовий чекаут. Повертає (response, email)."""
    data = _buyer_data(**over)
    response = client.post(
        f'/online-courses/{course.slug}/checkout', data=data,
        follow_redirects=False,
    )
    return response, data['email']


def _order_of(email):
    user = User.query.filter_by(email=email.lower()).one()
    return OnlineEnrollment.query.filter_by(user_id=user.id).one()


# ----------------------------- форма покупця -----------------------------

def test_anonymous_sees_buyer_form_instead_of_login(client, course):
    response = client.get(f'/online-courses/{course.slug}/checkout')

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'name="email"' in body
    assert 'name="consent_data"' in body


def test_buy_creates_passwordless_user_and_order(client, course):
    response, email = _buy(client, course)

    user = User.query.filter_by(email=email).one()
    assert not user.has_password
    assert user.last_name == 'Коваль'
    assert user.first_name == 'Ольга'

    enrollment = OnlineEnrollment.query.filter_by(user_id=user.id).one()
    assert enrollment.payment_amount == Decimal('4500')
    assert enrollment.payment_status == 'unpaid'
    assert enrollment.order_token
    assert response.status_code == 302
    assert f'/order/{enrollment.order_token}' in response.headers['Location']


def test_phone_is_optional(client, course):
    _buy(client, course, phone='')
    assert User.query.filter(User.email.like('guest-%')).count() >= 1


def test_consent_is_required(client, course):
    data = _buyer_data()
    data.pop('consent_data')
    response = client.post(f'/online-courses/{course.slug}/checkout', data=data)

    assert response.status_code == 200
    assert OnlineEnrollment.query.count() == 0


def test_invalid_email_does_not_create_anything(client, course):
    _buy(client, course, email='не-пошта')
    assert OnlineEnrollment.query.count() == 0


# ----------------------------- сторінка замовлення -----------------------------

def test_order_page_opens_without_login(client, course):
    _, email = _buy(client, course)
    enrollment = _order_of(email)

    response = client.get(f'/online-courses/order/{enrollment.order_token}')

    assert response.status_code == 200
    assert '4500' in response.get_data(as_text=True)


def test_order_page_never_leaks_access_url(client, course):
    _, email = _buy(client, course)
    enrollment = _order_of(email)

    body = client.get(
        f'/online-courses/order/{enrollment.order_token}').get_data(as_text=True)
    assert 'secret-guest' not in body


def test_unknown_token_is_gone(client, course):
    assert client.get('/online-courses/order/no-such-token').status_code == 410


def test_expired_token_is_gone(client, course):
    _, email = _buy(client, course)
    enrollment = _order_of(email)
    enrollment.order_token_expires_at = utcnow() - timedelta(days=1)
    db.session.commit()

    assert client.get(
        f'/online-courses/order/{enrollment.order_token}').status_code == 410


def test_cancelled_order_is_gone(client, course):
    _, email = _buy(client, course)
    enrollment = _order_of(email)
    enrollment.status = 'cancelled'
    db.session.commit()

    assert client.get(
        f'/online-courses/order/{enrollment.order_token}').status_code == 410


def test_order_page_is_not_stored_by_caches(client, course):
    """Сторінка показує чужу покупку тому, хто не залогінений.

    Публічний блупринт за замовчуванням отримує `private, no-cache` заради
    bfcache -- для цієї сторінки цього замало.
    """
    _, email = _buy(client, course)
    enrollment = _order_of(email)

    response = client.get(f'/online-courses/order/{enrollment.order_token}')
    assert 'no-store' in response.headers['Cache-Control']


# ----------------------------- наявний акаунт -----------------------------

def test_existing_order_sends_to_login_instead_of_duplicating(client, course):
    _, email = _buy(client, course)

    response = client.post(
        f'/online-courses/{course.slug}/checkout', data=_buyer_data(email=email))

    assert response.status_code == 302
    assert '/login' in response.headers['Location']
    assert OnlineEnrollment.query.count() == 1


def test_existing_account_keeps_its_name(client, course):
    user = User.create_with_password(
        f'known-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Оксана', last_name='Петренко', email_confirmed=True,
    )
    db.session.commit()

    _buy(client, course, email=user.email)

    db.session.refresh(user)
    assert user.last_name == 'Петренко'
    assert user.first_name == 'Оксана'


def test_existing_account_gets_no_password_offer(client, course):
    """Власнику акаунта пропонується вхід, а не новий пароль.

    Інакше будь-хто, вказавши чужу адресу на чекауті, отримав би форму
    зміни чужого пароля.
    """
    user = User.create_with_password(
        f'known-{uuid4().hex[:8]}@test.com', 'password123',
        first_name='Оксана', last_name='Петренко', email_confirmed=True,
    )
    db.session.commit()

    _buy(client, course, email=user.email)
    enrollment = OnlineEnrollment.query.filter_by(user_id=user.id).one()
    enrollment.payment_status = 'paid'
    enrollment.status = 'active'
    db.session.commit()

    body = client.get(
        f'/online-courses/order/{enrollment.order_token}').get_data(as_text=True)
    assert 'name="password_confirm"' not in body

    response = client.post(
        f'/online-courses/order/{enrollment.order_token}/set-password',
        data={'password': 'newpassword1', 'password_confirm': 'newpassword1'},
    )
    assert response.status_code == 302
    assert '/login' in response.headers['Location']
    db.session.refresh(user)
    assert user.check_password('password123')


# ----------------------------- кабінет після оплати -----------------------------

def _paid_order(client, course):
    _, email = _buy(client, course)
    enrollment = _order_of(email)
    enrollment.payment_status = 'paid'
    enrollment.status = 'active'
    db.session.commit()
    return enrollment


def test_password_form_appears_only_after_payment(client, course):
    _, email = _buy(client, course)
    enrollment = _order_of(email)

    body = client.get(
        f'/online-courses/order/{enrollment.order_token}').get_data(as_text=True)
    assert 'name="password_confirm"' not in body

    enrollment.payment_status = 'paid'
    db.session.commit()

    body = client.get(
        f'/online-courses/order/{enrollment.order_token}').get_data(as_text=True)
    assert 'name="password_confirm"' in body


def test_set_password_creates_account_and_logs_in(client, course):
    enrollment = _paid_order(client, course)

    response = client.post(
        f'/online-courses/order/{enrollment.order_token}/set-password',
        data={'password': 'newpassword1', 'password_confirm': 'newpassword1'},
    )

    assert response.status_code == 302
    assert '/account' in response.headers['Location']
    user = db.session.get(User, enrollment.user_id)
    assert user.has_password
    # Кабінет відкривається без окремого входу.
    assert client.get('/auth/account').status_code == 200


def test_short_password_is_rejected(client, course):
    enrollment = _paid_order(client, course)

    client.post(
        f'/online-courses/order/{enrollment.order_token}/set-password',
        data={'password': 'short', 'password_confirm': 'short'},
    )

    user = db.session.get(User, enrollment.user_id)
    assert not user.has_password


def test_mismatched_passwords_are_rejected(client, course):
    enrollment = _paid_order(client, course)

    client.post(
        f'/online-courses/order/{enrollment.order_token}/set-password',
        data={'password': 'newpassword1', 'password_confirm': 'newpassword2'},
    )

    user = db.session.get(User, enrollment.user_id)
    assert not user.has_password


# ----------------------------- гроші -----------------------------

def test_guest_can_apply_promo_code(client, course):
    from app.models.promo_code import PromoCode
    from app.services import promo_service

    code = f'GUEST{uuid4().hex[:6].upper()}'
    promo = PromoCode(
        code=code, code_norm=promo_service.normalize_code(code),
        discount_type='percent', discount_value=Decimal('10'),
    )
    db.session.add(promo)
    db.session.commit()

    _, email = _buy(client, course)
    enrollment = _order_of(email)

    client.post(f'/online-courses/order/{enrollment.order_token}',
                data={'promo_code': promo.code})

    db.session.refresh(enrollment)
    assert enrollment.promo_code_id == promo.id
    assert enrollment.discount_amount == Decimal('450.00')
    assert enrollment.payment_amount == Decimal('4050.00')


def test_access_email_points_guest_at_the_order_not_the_account(client, course, monkeypatch):
    """Кабінет не впустить покупця без пароля -- вести туди листом жорстоко."""
    from app.services.email_service import EmailService

    captured = {}

    def _fake_send(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(EmailService, 'send_email', staticmethod(_fake_send))
    monkeypatch.setattr(EmailService, '_site_base_url',
                        staticmethod(lambda: 'https://iprm.space'))

    enrollment = _paid_order(client, course)
    EmailService.send_online_access(enrollment, 'https://iprm.space/access/x')

    context = captured['context']
    assert context['guest_order'] is True
    assert enrollment.order_token in context['account_url']
    assert '/auth/account' not in context['account_url']


def test_access_email_leads_to_account_when_password_exists(client, course, monkeypatch):
    from app.services.email_service import EmailService

    captured = {}
    monkeypatch.setattr(EmailService, 'send_email',
                        staticmethod(lambda **kw: captured.update(kw)))
    monkeypatch.setattr(EmailService, '_site_base_url',
                        staticmethod(lambda: 'https://iprm.space'))

    enrollment = _paid_order(client, course)
    enrollment.user.set_password('password123')
    db.session.commit()

    EmailService.send_online_access(enrollment, 'https://iprm.space/access/x')

    assert captured['context']['guest_order'] is False
    assert captured['context']['account_url'].endswith('/auth/account')


# ----------------------------- локалі -----------------------------

@pytest.mark.parametrize('prefix', ['', '/ru', '/en'])
def test_guest_flow_works_in_every_locale(client, course, prefix):
    assert client.get(
        f'{prefix}/online-courses/{course.slug}/checkout').status_code == 200

    response = client.post(
        f'{prefix}/online-courses/{course.slug}/checkout', data=_buyer_data())
    assert response.status_code == 302
    assert f'{prefix}/online-courses/order/' in response.headers['Location']

    assert client.get(response.headers['Location']).status_code == 200


def test_invoice_by_token_is_refused_after_payment(client, course):
    """Рахунок «сплатіть ще раз» після оплати лише плутає."""
    enrollment = _paid_order(client, course)

    response = client.get(
        f'/online-courses/order/{enrollment.order_token}/invoice.pdf')

    assert response.status_code == 302
    assert f'/order/{enrollment.order_token}' in response.headers['Location']


def test_paid_order_page_has_no_payment_form(client, course):
    """Підписаний платіжний пакет на вже сплачену суму не створюємо.

    Перевіряємо саме пакет, а не слово "liqpay": скрипт віконця оплати
    підключений до сторінки завжди, і його наявність нічого не означає.
    """
    enrollment = _paid_order(client, course)

    body = client.get(
        f'/online-courses/order/{enrollment.order_token}').get_data(as_text=True)

    assert 'name="signature"' not in body
    assert 'data-liqpay-data' not in body


# ----------------------------- перевипуск доступу -----------------------------

def test_guest_can_reissue_an_expired_link(client, course, monkeypatch):
    """Гість із протермінованим токеном не має впиратись у логін.

    Сторінка помилки пропонує перевипуск лише власнику акаунта -- а в
    гостя його немає, тож без цього маршруту шлях закінчувався нічим.
    """
    from app.services import sintegrum_access

    enrollment = _paid_order(client, course)
    enrollment.access_token = 'stale-token'
    enrollment.access_expires_at = utcnow() - timedelta(hours=1)
    db.session.commit()

    monkeypatch.setattr(
        sintegrum_access, 'get_provider',
        lambda course=None, settings=None: _StubProvider(),
    )

    body = client.get(
        f'/online-courses/order/{enrollment.order_token}').get_data(as_text=True)
    assert 'Отримати нове посилання' in body

    response = client.post(
        f'/online-courses/order/{enrollment.order_token}/reissue')

    db.session.refresh(enrollment)
    assert response.status_code == 302
    assert enrollment.access_token != 'stale-token'
    assert f'/access/{enrollment.access_token}' in response.headers['Location']


def test_reissue_needs_a_paid_order(client, course):
    _, email = _buy(client, course)
    enrollment = _order_of(email)

    response = client.post(
        f'/online-courses/order/{enrollment.order_token}/reissue')

    db.session.refresh(enrollment)
    assert response.status_code == 302
    assert enrollment.access_token is None


def test_reissue_by_unknown_token_is_gone(client, course):
    assert client.post(
        '/online-courses/order/no-such-token/reissue').status_code == 410


class _StubProvider:
    """Партнера в тестах не смикаємо -- видача доступу тут не предмет."""

    def provision(self, enrollment):
        from app.services.sintegrum_access import AccessResult

        return AccessResult(target_url='https://acme.sintegrum.com')


def test_access_email_tells_the_buyer_how_to_log_in(client, course, monkeypatch):
    """Акаунт на платформі створюємо ми, а пароля до нього не маємо.

    API партнера не вміє ані видати пароль, ані надіслати запрошення --
    перевірено по документації. Тому лист мусить назвати логін і сказати,
    де поставити пароль: інакше людина впирається у форму входу з порожніми
    руками, як це сталося 20.08.2026.
    """
    from app.services.email_service import EmailService

    enrollment = _paid_order(client, course)
    rendered = {}

    def _fake_send(**kwargs):
        from flask import render_template
        rendered['html'] = render_template(
            f'emails/{kwargs["template_name"]}.html', **kwargs['context'])

    monkeypatch.setattr(EmailService, 'send_email', staticmethod(_fake_send))
    monkeypatch.setattr(EmailService, '_site_base_url',
                        staticmethod(lambda: 'https://iprm.space'))

    EmailService.send_online_access(enrollment, 'https://iprm.space/access/x')

    assert enrollment.user.email in rendered['html']
    assert 'Забули пароль' in rendered['html']
