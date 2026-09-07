"""Вимкнений LiqPay зникає зі сторінок, а не ламає їх.

Три речі, за якими тут доглядаємо.

Перша -- платіжний пакет не створюється взагалі, коли онлайн-оплату
вимкнено. Сховати кнопку в шаблоні, лишивши підписані дані в HTML, --
це не вимкнення, а маскування.

Друга -- на місці схованого LiqPay не лишається плашки «Онлайн-оплата
тимчасово недоступна». Вона означає поломку; в режимі «тільки рахунок»
нічого не поламано, і читати таке покупцеві нема за що.

Третя -- нова реєстрація в цьому режимі одразу позначається як оплата за
рахунком. Інакше адмінка й аналітика показували б «онлайн» для способу,
якого на сайті немає.
"""
import re
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from tests import refund_fixtures

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User

LIQPAY_FORM_MARKER = 'liqpay.ua/api/3/checkout'
LIQPAY_UNAVAILABLE = 'Онлайн-оплата тимчасово недоступна'


def _uid():
    return uuid4().hex[:6]


@pytest.fixture(autouse=True)
def _no_rate_limit():
    from app.extensions import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def clean(app):
    yield
    refund_fixtures.purge('pms-', 'pms-')


@pytest.fixture(autouse=True)
def _keys(liqpay_keys):
    """Без ключів форма не будується й так -- тест перевіряв би не те."""


@pytest.fixture
def methods(app):
    """Прапорці способів оплати з відновленням після тесту."""
    settings = SiteSettings.get()
    before = (settings.pay_liqpay_enabled, settings.pay_invoice_enabled)
    yield settings
    settings.pay_liqpay_enabled, settings.pay_invoice_enabled = before
    db.session.flush()


@pytest.fixture
def buyer(app):
    item = User.create_with_password(
        f'pms-{_uid()}@test.com', 'password123',
        first_name='Ігор', last_name='Мельник', email_confirmed=True,
    )
    db.session.flush()
    return item


@pytest.fixture
def instance(app):
    course = Course(title='Курс', slug=f'pms-{_uid()}', is_active=False)
    db.session.add(course)
    db.session.flush()
    item = CourseInstance(
        course_id=course.id, status='published', price=1000,
        start_date=utcnow() + timedelta(days=30),
    )
    db.session.add(item)
    db.session.flush()
    return item


@pytest.fixture
def unpaid_reg(app, buyer, instance):
    item = EventRegistration(
        user_id=buyer.id, instance_id=instance.id,
        phone='+380000000000', specialty='Лікар', workplace='Клініка',
        status='pending', payment_status='unpaid',
        payment_amount=Decimal('1000'),
    )
    db.session.add(item)
    db.session.flush()
    return item


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


class TestConfirmationPage:
    def test_liqpay_shown_by_default(self, client, buyer, unpaid_reg):
        _login(client, buyer)

        html = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

        assert LIQPAY_FORM_MARKER in html
        assert 'data-invoice-download' in html

    def test_liqpay_off_removes_payment_package(self, client, buyer, unpaid_reg, methods):
        methods.pay_liqpay_enabled = False
        db.session.flush()
        _login(client, buyer)

        html = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

        assert LIQPAY_FORM_MARKER not in html
        assert 'data-liqpay-data' not in html

    def test_liqpay_off_keeps_invoice(self, client, buyer, unpaid_reg, methods):
        methods.pay_liqpay_enabled = False
        db.session.flush()
        _login(client, buyer)

        html = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

        assert 'data-invoice-download' in html

    def test_liqpay_off_hides_unavailable_notice(self, client, buyer, unpaid_reg, methods):
        """Плашка про недоступність означає поломку, а тут нічого не зламано."""
        methods.pay_liqpay_enabled = False
        db.session.flush()
        _login(client, buyer)

        html = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

        assert LIQPAY_UNAVAILABLE not in html

    def test_invoice_off_keeps_liqpay(self, client, buyer, unpaid_reg, methods):
        methods.pay_invoice_enabled = False
        db.session.flush()
        _login(client, buyer)

        html = client.get(f'/registration/{unpaid_reg.id}').get_data(as_text=True)

        assert LIQPAY_FORM_MARKER in html
        assert 'data-invoice-download' not in html


class TestInvoiceRouteGuard:
    def test_invoice_off_closes_download(self, client, buyer, unpaid_reg, methods):
        """Схована кнопка -- не захист: адресу рахунка знають із листів."""
        methods.pay_invoice_enabled = False
        db.session.flush()
        _login(client, buyer)

        response = client.get(f'/registration/{unpaid_reg.id}/invoice.pdf')

        assert response.status_code == 404


class TestTokenFlow:
    def test_liqpay_off_removes_payment_package(self, client, unpaid_reg, methods):
        methods.pay_liqpay_enabled = False
        token = unpaid_reg.issue_completion_token()
        db.session.flush()

        html = client.get(f'/registration/complete/{token}/pay').get_data(as_text=True)

        assert LIQPAY_FORM_MARKER not in html
        assert 'Завантажити рахунок' in html


class TestNewRegistrationDefault:
    def test_defaults_to_invoice_when_liqpay_off(self, app, methods):
        """Спосіб оплати має описувати те, що людині справді пропонували."""
        methods.pay_liqpay_enabled = False
        db.session.flush()

        assert EventRegistration.default_payment_method() == 'invoice'

    def test_defaults_to_liqpay_when_enabled(self, app, methods):
        assert EventRegistration.default_payment_method() == 'liqpay'


class TestOnlineCourseOrder:
    @pytest.fixture
    def course(self, app):
        item = OnlineCourse(
            sintegrum_id=int(uuid4().int % 10_000_000),
            remote_name='Онлайн-курс',
            slug=f'pms-onl-{_uid()}',
            price=Decimal('4500'),
            access_url='https://example.test/register/x',
            is_published=True,
        )
        db.session.add(item)
        db.session.commit()
        yield item
        OnlineEnrollment.query.filter_by(online_course_id=item.id).delete()
        db.session.delete(item)
        db.session.commit()

    @pytest.fixture
    def enrollment(self, app, buyer, course):
        item = OnlineEnrollment(
            online_course_id=course.id, user_id=buyer.id,
            payment_status='unpaid', payment_amount=Decimal('4500'),
        )
        db.session.add(item)
        db.session.flush()
        return item

    def test_liqpay_off_removes_payment_package(self, client, buyer, enrollment,
                                                course, methods):
        methods.pay_liqpay_enabled = False
        db.session.flush()
        _login(client, buyer)

        html = client.get(
            f'/online-courses/{course.slug}/checkout').get_data(as_text=True)

        assert LIQPAY_FORM_MARKER not in html

    def test_liqpay_off_keeps_invoice(self, client, buyer, enrollment, course, methods):
        methods.pay_liqpay_enabled = False
        db.session.flush()
        _login(client, buyer)

        html = client.get(
            f'/online-courses/{course.slug}/checkout').get_data(as_text=True)

        assert 'Завантажити рахунок' in html
        assert LIQPAY_UNAVAILABLE not in html

    def test_sole_method_gets_the_primary_button(self, client, buyer, enrollment,
                                                 course, methods):
        """Єдина дія сторінки не сміє лишатись виноскою.

        Посилання на рахунок жило у слоті-виносці під кнопкою LiqPay -- і це
        було правильно, доки воно було другорядним шляхом. Ставши єдиним
        способом оплати, воно мусить зайняти той самий слот і той самий
        компонент, що й кнопка, яку замінило.
        """
        methods.pay_liqpay_enabled = False
        db.session.flush()
        _login(client, buyer)

        html = client.get(
            f'/online-courses/{course.slug}/checkout').get_data(as_text=True)

        assert re.search(
            r'<a[^>]+invoice\.pdf"[^>]+class="apple-btn apple-btn--primary'
            r' apple-btn--full"', html,
        ), 'рахунок мав стати первинною кнопкою'

    def test_sole_method_drops_the_warning_styling(self, client, buyer, enrollment,
                                                   course, methods):
        """Інструкція «як платити» -- не попередження.

        iprm-online-buy__note малює жовту плашку (--iprm-warning-bg): нею
        кажуть, що щось пішло не так. Звичайний спосіб оплати в ній читався
        як аварія, а справжня дія поруч лишалась сірим текстом.
        """
        methods.pay_liqpay_enabled = False
        db.session.flush()
        _login(client, buyer)

        html = client.get(
            f'/online-courses/{course.slug}/checkout').get_data(as_text=True)

        assert 'iprm-online-buy__note' not in html

    def test_secondary_invoice_stays_a_footnote(self, client, buyer, enrollment,
                                                course, methods):
        """З увімкненим LiqPay рахунок другорядний -- кнопкою його робити не треба."""
        _login(client, buyer)

        html = client.get(
            f'/online-courses/{course.slug}/checkout').get_data(as_text=True)

        assert 'Платите від організації?' in html
        assert not re.search(
            r'<a[^>]+invoice\.pdf"[^>]+class="apple-btn', html,
        )

    def test_free_course_gets_no_invoice_button(self, client, buyer, enrollment,
                                                course, methods):
        """Рахунка на нуль не буває -- кнопка вела б у глухий кут.

        _send_invoice на таке замовлення відповідає «для безкоштовного
        рахунок не потрібен», тож пропонувати його означало б вести людину
        по колу.
        """
        methods.pay_liqpay_enabled = False
        enrollment.payment_amount = Decimal('0')
        course.price = Decimal('0')
        db.session.flush()
        _login(client, buyer)

        html = client.get(
            f'/online-courses/{course.slug}/checkout').get_data(as_text=True)

        assert not re.search(r'<a[^>]+invoice\.pdf"[^>]+class="apple-btn', html)
