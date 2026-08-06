"""Гостьова покупка: реєстрація на курс без акаунта.

Вхід перед оплатою був найбільшим бар'єром воронки. Тепер користувач
створюється безпарольним на сабміті (тим самим resolve_user, яким уже
користуються адмінські імпорти), а далі людину веде публічний
токен-флоу -- той самий, що й для учасників, доданих менеджером.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.registration import EventRegistration
from app.models.user import User


@pytest.fixture(autouse=True)
def _no_rate_limit(app):
    """Ліміт 10 POST/год на IP -- реальний захист, але в тестах він
    спрацьовує вже на одинадцятій покупці й ховає справжні падіння."""
    from app.extensions import limiter
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def _no_recaptcha(monkeypatch):
    """reCAPTCHA лишається увімкненою в проді -- вона єдиний бар'єр від
    ботів після зняття логіну. У тестах вимикаємо перевірку."""
    monkeypatch.setattr('app.registration.routes.verify_recaptcha',
                        lambda action=None: True)


def _instance(price=1000, event_format='online', with_tariff=False):
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=f'g-{uuid4().hex[:6]}',
                    is_active=True, event_type='course')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='published', event_format=event_format,
        price=price, start_date=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(inst)
    db.session.flush()
    if with_tariff:
        db.session.add(InstanceTariff(
            instance_id=inst.id, name='Онлайн', price=price,
            event_format='online', sort_order=0, is_active=True))
    db.session.commit()
    return inst


def _url(inst):
    return f'/registration/instance/{inst.id}/register'


def _payload(**over):
    data = {
        'last_name': 'Гостьовий',
        'first_name': 'Тест',
        'email': f'guest-{uuid4().hex[:6]}@test.com',
        'phone': '+380501112233',
        'consent_data': 'y',
    }
    data.update(over)
    return data


# --- доступ до форми --------------------------------------------------------

def test_form_opens_without_login(client):
    """Раніше тут був редирект на /auth/login."""
    inst = _instance()
    resp = client.get(_url(inst))
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'name="email"' in html
    assert 'Уже маєте кабінет' in html


def test_logged_in_user_does_not_see_email_field(client):
    """Залогіненому email відомий -- зайве поле у воронці."""
    user = User.create_with_password(
        f'u-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True)
    db.session.commit()
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)

    inst = _instance()
    html = client.get(_url(inst)).get_data(as_text=True)
    assert 'name="email"' not in html
    assert 'Уже маєте кабінет' not in html


# --- покупка ----------------------------------------------------------------

def test_guest_purchase_creates_user_and_registration(client):
    inst = _instance()
    data = _payload()
    resp = client.post(_url(inst), data=data)
    assert resp.status_code == 302

    user = User.query.filter_by(email=data['email']).one()
    # Пароль живе в AuthIdentity, а не в User: у гостя його ще немає.
    from app.models.auth_identity import AuthIdentity
    assert AuthIdentity.query.filter_by(
        user_id=user.id, provider=AuthIdentity.PROVIDER_PASSWORD).count() == 0
    assert user.first_name == 'Тест'

    reg = EventRegistration.query.filter_by(user_id=user.id,
                                            instance_id=inst.id).one()
    assert reg.phone == '+380501112233'
    # Далі людину веде токен: сторінка підтвердження вимагає логіну.
    assert reg.completion_token
    assert f'/registration/complete/{reg.completion_token}' in resp.headers['Location']


def test_guest_lands_on_public_page_after_purchase(client):
    inst = _instance()
    resp = client.post(_url(inst), data=_payload(), follow_redirects=True)
    assert resp.status_code == 200
    # Публічна сторінка відкрилась без входу.
    assert 'auth/login' not in resp.request.path


def test_email_is_required_for_guest(client):
    inst = _instance()
    data = _payload()
    del data['email']
    resp = client.post(_url(inst), data=data)
    assert resp.status_code == 200                  # форма з помилкою
    assert EventRegistration.query.filter_by(instance_id=inst.id).count() == 0


def test_invalid_email_is_rejected(client):
    inst = _instance()
    resp = client.post(_url(inst), data=_payload(email='не-пошта'))
    assert resp.status_code == 200
    assert EventRegistration.query.filter_by(instance_id=inst.id).count() == 0


def test_guest_purchase_with_tariff(client):
    inst = _instance(with_tariff=True)
    tariff = inst.tariffs[0]
    resp = client.post(_url(inst), data=_payload(tariff_id=str(tariff.id)))
    assert resp.status_code == 302
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.tariff_id == tariff.id


# --- email наявного акаунта -------------------------------------------------

def test_existing_email_attaches_to_that_account(client):
    """Рішення 31.07.2026: оплату не блокуємо, реєстрація лягає в наявний
    кабінет, доступ людина отримає входом."""
    owner = User.create_with_password(
        f'own-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Власник', last_name='Акаунта', email_confirmed=True)
    db.session.commit()
    before = User.query.count()

    inst = _instance()
    resp = client.post(_url(inst), data=_payload(email=owner.email))
    assert resp.status_code == 302
    assert User.query.count() == before, 'дубль користувача не створюємо'

    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.user_id == owner.id


def test_second_purchase_of_same_event_is_refused(client):
    inst = _instance()
    data = _payload()
    client.post(_url(inst), data=data)

    resp = client.post(_url(inst), data=data)
    assert resp.status_code == 302
    assert 'auth/login' in resp.headers['Location']
    assert EventRegistration.query.filter_by(instance_id=inst.id).count() == 1


# --- захист -----------------------------------------------------------------

def test_recaptcha_still_guards_the_route(client, monkeypatch):
    """Логін був неявним бар'єром від ботів; після його зняття лишається
    reCAPTCHA -- перевіряємо, що вона справді блокує."""
    monkeypatch.setattr('app.registration.routes.verify_recaptcha',
                        lambda action=None: False)
    inst = _instance()
    resp = client.post(_url(inst), data=_payload())
    assert resp.status_code == 200
    assert EventRegistration.query.filter_by(instance_id=inst.id).count() == 0


def test_consent_is_still_required(client):
    inst = _instance()
    data = _payload()
    del data['consent_data']
    resp = client.post(_url(inst), data=data)
    assert resp.status_code == 200
    assert EventRegistration.query.filter_by(instance_id=inst.id).count() == 0


# --- створення кабінету після покупки ---------------------------------------

def _buy(client, inst, **over):
    """Гостьова покупка -> (реєстрація, токен)."""
    client.post(_url(inst), data=_payload(**over))
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    return reg, reg.completion_token


def test_pay_page_offers_account_creation(client):
    inst = _instance()
    reg, token = _buy(client, inst)
    html = client.get(f'/registration/complete/{token}/pay').get_data(as_text=True)
    assert 'Створіть кабінет' in html
    assert 'name="password"' in html


def test_guest_can_set_password_and_gets_logged_in(client):
    from app.models.auth_identity import AuthIdentity
    inst = _instance()
    reg, token = _buy(client, inst)

    resp = client.post(f'/registration/complete/{token}/set-password',
                       data={'password': 'secret12345',
                             'password_confirm': 'secret12345'})
    assert resp.status_code == 302
    assert '/auth/account' in resp.headers['Location']

    user = db.session.get(User, reg.user_id)
    assert AuthIdentity.query.filter_by(
        user_id=user.id, provider=AuthIdentity.PROVIDER_PASSWORD).count() == 1
    assert user.check_password('secret12345')
    # Людина одразу в кабінеті, без окремого входу.
    with client.session_transaction() as sess:
        assert sess.get('_user_id') == str(user.id)


@pytest.mark.parametrize('data', [
    {'password': 'short', 'password_confirm': 'short'},
    {'password': 'secret12345', 'password_confirm': 'inshiy12345'},
])
def test_weak_or_mismatched_password_refused(client, data):
    from app.models.auth_identity import AuthIdentity
    inst = _instance()
    reg, token = _buy(client, inst)
    client.post(f'/registration/complete/{token}/set-password', data=data)
    assert AuthIdentity.query.filter_by(
        user_id=reg.user_id, provider=AuthIdentity.PROVIDER_PASSWORD).count() == 0


def test_cannot_overwrite_password_of_existing_account(client):
    """Інакше будь-хто, вказавши чужий email на чекауті, змінив би пароль
    власника і забрав акаунт."""
    owner = User.create_with_password(
        f'own-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Власник', last_name='Акаунта', email_confirmed=True)
    db.session.commit()

    inst = _instance()
    reg, token = _buy(client, inst, email=owner.email)
    assert reg.user_id == owner.id

    resp = client.post(f'/registration/complete/{token}/set-password',
                       data={'password': 'attacker123',
                             'password_confirm': 'attacker123'})
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']

    fetched = db.session.get(User, owner.id)
    assert fetched.check_password('password123'), 'старий пароль має лишитись'
    assert not fetched.check_password('attacker123')


def test_existing_account_sees_login_hint_not_form(client):
    owner = User.create_with_password(
        f'own-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Власник', last_name='Акаунта', email_confirmed=True)
    db.session.commit()
    inst = _instance()
    _reg, token = _buy(client, inst, email=owner.email)

    html = client.get(f'/registration/complete/{token}/pay').get_data(as_text=True)
    assert 'Створіть кабінет' not in html
    assert 'наявного кабінету' in html


def test_invalid_token_cannot_set_password(client):
    resp = client.post('/registration/complete/deadbeef/set-password',
                       data={'password': 'secret12345',
                             'password_confirm': 'secret12345'})
    assert resp.status_code == 410


# --- лист гостю -------------------------------------------------------------

def test_email_pay_link_is_public_for_guest(client):
    """Лист вів на /registration/<id>, який вимагає входу -- гість упирався
    б у логін уже в пошті."""
    from app.services.email_service import EmailService
    inst = _instance()
    reg, token = _buy(client, inst)

    url = EmailService._pay_url_for_registration(reg)
    assert f'/registration/complete/{token}/pay' in url
    assert f'/registration/{reg.id}' not in url


def test_email_pay_link_stays_private_for_account_holder(client):
    from app.services.email_service import EmailService
    owner = User.create_with_password(
        f'own-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Власник', last_name='Акаунта', email_confirmed=True)
    db.session.commit()
    with client.session_transaction() as s:
        s['_user_id'] = str(owner.id)

    inst = _instance()
    client.post(_url(inst), data=_payload(email=owner.email))
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.completion_token is None      # залогінений іде звичайним шляхом
    assert f'/registration/{reg.id}' in EmailService._pay_url_for_registration(reg)


def test_has_password_reflects_identity(client):
    inst = _instance()
    reg, token = _buy(client, inst)
    user = db.session.get(User, reg.user_id)
    assert user.has_password is False

    client.post(f'/registration/complete/{token}/set-password',
                data={'password': 'secret12345', 'password_confirm': 'secret12345'})
    assert db.session.get(User, reg.user_id).has_password is True


# --- реферальна атрибуція переживає анонімний шлях ---------------------------

def test_referral_cookie_is_attributed_to_guest_purchase(client):
    from app.services import referral_service
    referrer = User.create_with_password(
        f'ref-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Рефер', last_name='Ер', email_confirmed=True)
    db.session.commit()
    code = referral_service.ensure_referral_code(referrer, 'u')
    db.session.commit()

    client.set_cookie(referral_service.REF_COOKIE, code)
    inst = _instance()
    client.post(_url(inst), data=_payload())

    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()
    assert reg.referral_code == code


def test_pay_page_shows_delivery_email(client):
    """Одруківка в email = оплата без доступу, і людина дізнається
    найпізніше. Показуємо адресу одразу."""
    inst = _instance()
    data = _payload()
    client.post(_url(inst), data=data)
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()

    html = client.get(
        f'/registration/complete/{reg.completion_token}/pay').get_data(as_text=True)
    assert data['email'] in html
    assert 'Адреса з помилкою?' in html


def test_sent_email_body_links_to_public_page(client, monkeypatch):
    """Регресія на порядок дій: лист відправлявся ДО видачі токена, тож
    _pay_url_for_registration бачив None і будував посилання на роут із
    логіном. Перевіряємо тіло вже НАДІСЛАНОГО листа, а не саму функцію --
    інакше баг у порядку викликів лишається невидимим."""
    from app.models.email_log import EmailLog
    from app.models.email_settings import EmailSettings
    # Попередні покупки в цьому файлі писали failed-логи (пошта вимкнена),
    # і circuit breaker відсікав би відправку ще до рендеру шаблону.
    EmailLog.query.delete()
    db.session.commit()

    settings = EmailSettings.get()
    settings.is_enabled = True
    settings.smtp_server, settings.smtp_port = 'localhost', 25
    settings.smtp_username = settings.default_sender = 'noreply@test.local'
    db.session.commit()
    monkeypatch.setattr('app.services.email_service.Thread',
                        lambda *a, **kw: type('T', (), {
                            'start': lambda self: None, 'daemon': True})())

    inst = _instance()
    client.post(_url(inst), data=_payload())
    reg = EventRegistration.query.filter_by(instance_id=inst.id).one()

    # Лист неоплаченої реєстрації тепер відкладений (щоб той, хто платить
    # одразу, не отримав "до оплати" під час платежу). Проганяємо чергу
    # вручну -- саме тим викликом, який робить планувальник.
    from app.models.mixins import utcnow
    from app.services.email_service import EmailService
    assert reg.confirmation_email_due_at is not None, 'лист не поставлено в чергу'
    reg.confirmation_email_due_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    EmailService.send_due_registration_confirmations()

    # Саме шаблон учасника: send_registration_confirmation слідом шле ще
    # й нотифікацію адміну, і вона була б "останнім" логом реєстрації.
    log = (EmailLog.query
           .filter_by(registration_id=reg.id,
                      template_name='registration_confirmed')
           .order_by(EmailLog.id.desc()).first())
    assert log is not None and log.html_body, 'лист не сформувався'
    assert f'/registration/complete/{reg.completion_token}/pay' in log.html_body
    assert 'Створити кабінет' in log.html_body

    settings.is_enabled = False
    db.session.commit()
