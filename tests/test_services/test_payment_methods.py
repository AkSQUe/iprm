"""Перемикач способів оплати: LiqPay і оплата на рахунок IBAN.

Головне, що тут стережеться, -- запобіжник «вимкнено обидва». Платний
захід без жодного способу оплати це глухий кут для покупця, і жоден стан
налаштувань не сміє його створити.

Друге за важливістю -- межа між `is_configured` і `liqpay_checkout_enabled`.
Перше означає «ключі на місці» і потрібне колбеку, звірці й поверненням
коштів; друге -- «приймаємо нові платежі». Якщо їх сплутати, вимкнений
перемикач обірве обробку платежів, що вже в дорозі.
"""
import pytest

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.services.liqpay import liqpay_checkout_enabled


@pytest.fixture
def settings(app):
    item = SiteSettings.get()
    before = (item.pay_liqpay_enabled, item.pay_invoice_enabled)
    yield item
    item.pay_liqpay_enabled, item.pay_invoice_enabled = before
    db.session.flush()


class TestEnabledPaymentMethods:
    def test_both_enabled_by_default(self, settings):
        """Дефолт відтворює поведінку до появи перемикача."""
        assert settings.pay_liqpay_enabled is True
        assert settings.pay_invoice_enabled is True

        methods = SiteSettings.enabled_payment_methods()

        assert methods.liqpay is True
        assert methods.invoice is True

    def test_liqpay_off_leaves_invoice(self, settings):
        settings.pay_liqpay_enabled = False
        db.session.flush()

        methods = SiteSettings.enabled_payment_methods()

        assert methods.liqpay is False
        assert methods.invoice is True

    def test_invoice_off_leaves_liqpay(self, settings):
        settings.pay_invoice_enabled = False
        db.session.flush()

        methods = SiteSettings.enabled_payment_methods()

        assert methods.liqpay is True
        assert methods.invoice is False

    def test_both_off_falls_back_to_invoice(self, settings):
        """Запобіжник: рахунок лишається, бо він не залежить від чужого API."""
        settings.pay_liqpay_enabled = False
        settings.pay_invoice_enabled = False
        db.session.flush()

        methods = SiteSettings.enabled_payment_methods()

        assert methods.liqpay is False
        assert methods.invoice is True

    def test_accepts_preloaded_settings(self, settings):
        """Виклик із уже завантаженим рядком -- без повторного запиту."""
        settings.pay_liqpay_enabled = False
        db.session.flush()

        assert SiteSettings.enabled_payment_methods(settings).liqpay is False


class TestLiqpayCheckoutEnabled:
    def test_keys_and_flag(self, settings, liqpay_keys):
        assert liqpay_checkout_enabled() is True

    def test_flag_off_hides_checkout(self, settings, liqpay_keys):
        settings.pay_liqpay_enabled = False
        db.session.flush()

        assert liqpay_checkout_enabled() is False

    def test_flag_off_keeps_keys_configured(self, settings, liqpay_keys):
        """Колбек, звірка й повернення коштів мусять працювати далі.

        Гроші, які вже пішли, не питають про перемикач в адмінці.
        """
        from app.services.liqpay import get_liqpay_service

        settings.pay_liqpay_enabled = False
        db.session.flush()

        assert get_liqpay_service().is_configured is True
