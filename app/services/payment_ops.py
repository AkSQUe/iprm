"""
DB-aware payment operations.

Single code path for all payment status transitions.
Uses row-level locking to prevent race conditions.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from app.extensions import db
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.payment_transaction import PaymentTransaction

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

STATUS_MAP = {
    'success': 'paid',
    'sandbox': 'paid',
    'failure': 'unpaid',
    'error': 'unpaid',
    'processing': 'pending',
    'wait_accept': 'pending',
    'reversed': 'refunded',
}

ALLOWED_TRANSITIONS = {
    'unpaid': {'pending', 'paid', 'refunded'},
    'pending': {'paid', 'refunded'},
    'paid': {'refunded'},
    'refunded': set(),
}

PERMANENT_ERRORS = frozenset({
    'invalid signature', 'unknown order_id', 'invalid order_id',
    'amount mismatch', 'invalid amount',
})

# Один текст на обидва типи замовлень: адмін бачить те саме повідомлення
# незалежно від того, за що він повертає гроші.
LIQPAY_UNREACHABLE = "Не вдалося з'єднатися з LiqPay API"


def _fail(msg):
    db.session.rollback()
    return False, msg


def _noop(msg):
    db.session.rollback()
    return True, msg


def _log_transaction(reg_id, order_id, mapped_status, source,
                     liqpay_status=None, payment_id=None,
                     amount=None, raw_payload=None, enrollment_id=None):
    """Зберегти запис в журнал платіжних транзакцій.

    Журнал спільний для обох типів замовлень: заповнюється рівно одне з
    полів reg_id / enrollment_id (це закріплено CHECK-ом у БД).
    """
    try:
        txn = PaymentTransaction(
            registration_id=reg_id,
            enrollment_id=enrollment_id,
            order_id=order_id,
            liqpay_status=liqpay_status,
            mapped_status=mapped_status,
            source=source,
            payment_id=payment_id,
            amount=amount,
            raw_payload=raw_payload,
        )
        db.session.add(txn)
    except Exception:
        logger.exception('Failed to log payment transaction for %s', order_id)


def check_amount(expected, actual, order_id):
    """Звірка суми, спільна для обох типів замовлень.

    Повертає None, якщо все гаразд, інакше -- рядок-причину відмови.
    Виносимо саме сюди: розбіжність у правилах звірки між типами
    замовлень означала б, що одне з них можна оплатити не тією сумою.

    `expected is None` -- сума не зафіксована (історичні рядки), звіряти
    нема з чим. А ось нуль звіряємо нарівні з рештою: замовлення на нуль
    гривень (знижка 100%) не має мовчки приймати будь-який платіж.
    """
    if expected is None or actual is None:
        return None
    try:
        if abs(float(actual) - float(expected)) > 0.01:
            logger.warning('Payment amount mismatch %s: expected %s, got %s',
                           order_id, expected, actual)
            return 'amount mismatch'
    except (TypeError, ValueError):
        logger.warning('Payment invalid amount for %s', order_id)
        return 'invalid amount'
    return None


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def resolve_refund_amount(order, requested):
    """Сума до повернення: перевірена, округлена до копійки.

    Повертає (Decimal, None) або (None, причина відмови). `requested is
    None` означає «решту», тобто повне повернення того, що ще не повернуто.

    Перевірка робиться ПІД блокуванням рядка (див. виклики): без цього два
    адміни, що відкрили картку одночасно, обидва побачили б повний залишок
    і повернули б суму двічі.

    Стеля -- `refund_available`, а не `refund_remaining`: LiqPay поверне
    лише те, що надійшло на ЦЕЙ order_id, а доплата різниці тарифу при
    перенесенні приходила на власний SUR-. Без цієї межі повернення
    первісної суми відхилялося б цілком -- і адмін не міг би повернути
    навіть її.
    """
    remaining = order.refund_available
    if remaining <= 0:
        return None, 'За цим замовленням уже повернуто всю суму'

    if requested is None or requested == '':
        return remaining, None

    try:
        parsed = Decimal(str(requested).replace(',', '.').strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None, 'Некоректна сума повернення'

    # NaN і нескінченність -- теж валідні Decimal, але порівнювати їх не
    # можна: `Decimal('NaN') <= 0` не повертає False, а піднімає
    # InvalidOperation. Без цієї перевірки рядок "nan" у полі суми клав
    # сторінку повернення 500-ю замість повідомлення про помилку.
    if not parsed.is_finite():
        return None, 'Некоректна сума повернення'

    amount = _money(parsed)

    if amount <= 0:
        return None, 'Сума повернення має бути більшою за нуль'
    if amount > remaining:
        return None, f'Сума перевищує доступний залишок ({remaining} грн)'
    return amount, None


def _fill_full_refund(order):
    """Дописати суму повернення, якщо перехід у 'refunded' прийшов ззовні.

    Наші власні виклики (`initiate_refund`) заповнюють `refunded_amount` до
    зміни статусу. Але статус 'refunded' може прийти й callback-ом після
    повернення в кабінеті LiqPay, і ручним оновленням адміном -- тоді сума
    лишилась би нулем, а звірка показала б «повернено 0 грн» за
    поверненим замовленням.
    """
    if order.refunded_total > 0:
        return
    order.refunded_amount = _money(order.payment_amount)
    order.refunded_at = datetime.now(timezone.utc)


def _is_partial_refund_echo(order):
    """Чи є зовнішній сигнал `reversed` луною нашого часткового повернення.

    LiqPay повідомляє про повернення тим самим статусом `reversed`, і
    `check_status` віддає його ж. Якщо ми повернули половину, такий сигнал
    без цієї перевірки перевів би замовлення у 'refunded' цілком: людина
    втратила б місце на заході, за яке половина грошей лишилась у нас.

    Нуль повернень -- інша ситуація: повернення провели повз систему (у
    кабінеті LiqPay), і його треба прийняти як повне.
    """
    return order.has_refund and not order.is_fully_refunded


def parse_order_id(order_id):
    """Розібрати order_id у пару (тип, числовий id).

    Типи: 'registration' (REG-<id>), 'enrollment' (ONL-<id>) і
    'surcharge' (SUR-<transfer_id>) -- доплата різниці тарифу при
    перенесенні. Останній вказує на RegistrationTransfer, а не на
    реєстрацію: сума й підстава живуть саме там.
    """
    for prefix, kind in (('REG-', 'registration'), ('ONL-', 'enrollment'),
                         ('SUR-', 'surcharge')):
        if order_id.startswith(prefix):
            try:
                return kind, int(order_id.split('-', 1)[1])
            except (ValueError, IndexError):
                return kind, None
    return None, None


class PaymentOps:

    def __init__(self, liqpay_service):
        self.liqpay = liqpay_service

    def process_callback(self, data_base64, signature):
        if not self.liqpay.validate_callback_signature(data_base64, signature):
            logger.warning('LiqPay callback: invalid signature')
            return False, 'invalid signature'

        payload = self.liqpay.decode_callback(data_base64)
        order_id = payload.get('order_id', '')
        liqpay_status = payload.get('status', '')
        payment_id = str(payload.get('payment_id', ''))

        kind, object_id = parse_order_id(order_id)
        if kind is None:
            logger.warning('LiqPay callback: unknown order_id: %s', order_id)
            return False, 'unknown order_id'
        if object_id is None:
            logger.warning('LiqPay callback: malformed order_id: %s', order_id)
            return False, 'invalid order_id'

        if kind == 'enrollment':
            return self._process_enrollment_callback(
                object_id, payload, liqpay_status, payment_id,
            )

        if kind == 'surcharge':
            from app.models.registration_transfer import RegistrationTransfer
            # Блокування рядка -- як і для REG-/ONL- нижче/вище: два callback-и
            # (справжній retry LiqPay і паралельна ручна звірка) інакше обидва
            # прочитали б surcharge_paid_at=None і зарахували різницю двічі.
            transfer = (
                db.session.query(RegistrationTransfer)
                .with_for_update().populate_existing()
                .filter_by(id=object_id).first()
            )
            if transfer is None:
                return _fail(f'Перенесення #{object_id} не знайдено')
            new_status = STATUS_MAP.get(liqpay_status)
            if new_status != 'paid':
                return _noop(f'Доплата #{object_id}: статус {liqpay_status}')
            # transfer.difference -- знімок на момент перенесення й ЄДИНЕ
            # джерело правди про суму; payload -- лише свідчення, яке звіряємо
            # з ним (як check_amount нижче звіряє payload з reg.payment_amount).
            # Якщо вони розходяться -- гроші, що не сходяться, і зарахувати
            # мовчки не можна.
            problem = check_amount(
                transfer.difference, payload.get('amount'), f'SUR-{object_id}')
            if problem:
                return _fail(problem)
            applied = self.apply_surcharge(
                transfer, payment_id=payment_id, amount=transfer.difference,
            )
            if applied:
                return _noop(f'Доплату за перенесенням #{object_id} зараховано')
            return _noop(f'Доплата за перенесенням #{object_id} вже зарахована')

        reg_id = object_id
        reg = (
            db.session.query(EventRegistration)
            .with_for_update().populate_existing()
            .filter_by(id=reg_id).first()
        )
        if not reg:
            logger.warning('LiqPay callback: registration %d not found', reg_id)
            return False, 'registration not found'

        new_status = STATUS_MAP.get(liqpay_status)
        if not new_status:
            logger.warning('LiqPay callback: unknown status %s', liqpay_status)
            return _fail(f'unknown status: {liqpay_status}')

        if reg.payment_status == new_status and reg.payment_id == payment_id:
            return _noop('already processed')

        callback_amount = payload.get('amount')
        return self.update_payment_status(
            reg, new_status, payment_id, amount=callback_amount,
            source='callback', liqpay_status=liqpay_status,
            raw_payload=payload,
        )

    # ---- онлайн-курси (order_id ONL-<id>) ----

    def _process_enrollment_callback(self, enrollment_id, payload,
                                     liqpay_status, payment_id):
        from app.models.online_enrollment import OnlineEnrollment

        enrollment = (
            db.session.query(OnlineEnrollment)
            .with_for_update().populate_existing()
            .filter_by(id=enrollment_id).first()
        )
        if not enrollment:
            logger.warning('LiqPay callback: enrollment %d not found', enrollment_id)
            return False, 'enrollment not found'

        new_status = STATUS_MAP.get(liqpay_status)
        if not new_status:
            logger.warning('LiqPay callback: unknown status %s', liqpay_status)
            return _fail(f'unknown status: {liqpay_status}')

        if enrollment.payment_status == new_status and enrollment.payment_id == payment_id:
            return _noop('already processed')

        return self.update_enrollment_status(
            enrollment, new_status, payment_id, amount=payload.get('amount'),
            source='callback', liqpay_status=liqpay_status, raw_payload=payload,
        )

    def update_enrollment_status(self, enrollment, new_status, payment_id=None,
                                 amount=None, source='manual', liqpay_status=None,
                                 raw_payload=None):
        """Перехід статусу оплати для замовлення онлайн-курсу.

        Правила переходів і звірка суми -- спільні з реєстраціями
        (ALLOWED_TRANSITIONS, check_amount). Відрізняються лише наслідки:
        тут немає ані місць, ані тарифів, ані сертифікатів -- лише видача
        доступу, і та окремою транзакцією ПІСЛЯ фіксації оплати.
        """
        order_id = enrollment.order_id

        if new_status == 'paid':
            problem = check_amount(enrollment.payment_amount, amount, order_id)
            if problem:
                return _fail(problem)

        if (new_status == 'refunded' and source != 'refund'
                and _is_partial_refund_echo(enrollment)):
            logger.info('Partial refund echo ignored for %s (%s of %s returned)',
                        order_id, enrollment.refunded_total,
                        enrollment.payment_amount)
            return _noop('partial refund already recorded')

        if new_status not in ALLOWED_TRANSITIONS.get(enrollment.payment_status, set()):
            logger.warning('Payment invalid transition %s -> %s for %s',
                           enrollment.payment_status, new_status, order_id)
            return _noop('no-op transition')

        enrollment.payment_status = new_status
        if payment_id:
            enrollment.payment_id = payment_id

        if new_status == 'paid':
            enrollment.paid_at = datetime.now(timezone.utc)
            enrollment.status = 'active'
        elif new_status == 'refunded':
            enrollment.status = 'cancelled'
            _fill_full_refund(enrollment)
            # Повернення коштів забирає доступ: інакше людина лишалася б із
            # відкритим курсом, за який гроші вже повернуто. Тут -- ЛИШЕ наш
            # токен: звернення до Sintegrum іде після коміту, бо його
            # таймаути тримали б заблокований рядок під час callback LiqPay.
            from app.services import sintegrum_access
            sintegrum_access.revoke_local(enrollment)

        _log_transaction(
            reg_id=None, enrollment_id=enrollment.id, order_id=order_id,
            mapped_status=new_status, source=source,
            liqpay_status=liqpay_status, payment_id=payment_id,
            amount=amount, raw_payload=raw_payload,
        )

        try:
            db.session.commit()
            logger.info('Payment %s -> %s', order_id, new_status)
        except Exception:
            logger.exception('Payment DB error for %s', order_id)
            return _fail('db error')

        # Промокод: повернення коштів звільняє використання у ліміті -- код
        # можна видати комусь іншому. Знімок знижки на замовленні лишається
        # (історія платежу не переписується). Best-effort, як і для
        # реєстрацій: збій тут не має відкочувати вже зафіксовану оплату.
        try:
            from app.services import promo_service
            if promo_service.sync_for_enrollment(enrollment) is not None:
                db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Promo sync failed for %s', order_id)

        # Зняття доступу в Sintegrum -- поза транзакцією, best-effort.
        if new_status == 'refunded':
            try:
                from app.services import sintegrum_access
                sintegrum_access.revoke_remote(enrollment)
            except Exception:
                logger.exception('Failed to revoke remote access for %s', order_id)

        # Видача доступу -- ПІСЛЯ коміту оплати й окремою транзакцією.
        # Якщо вона впаде, замовлення лишиться оплаченим і без доступу:
        # це видимий стан, який підбирає джоба. Зворотний порядок відкотив
        # би оплату -- гроші прийшли б, а система вважала б, що ні.
        if new_status == 'paid':
            try:
                from app.services import sintegrum_access
                sintegrum_access.provision_and_notify(enrollment)
            except Exception:
                db.session.rollback()
                logger.exception('Failed to provision access for %s', order_id)

        return True, 'ok'

    # ---- реєстрації на заходи (order_id REG-<id>) ----

    def update_payment_status(self, reg, new_status, payment_id=None, amount=None,
                              source='manual', liqpay_status=None, raw_payload=None):
        if new_status == 'paid':
            problem = check_amount(reg.payment_amount, amount, f'REG-{reg.id}')
            if problem:
                return _fail(problem)

        if (new_status == 'refunded' and source != 'refund'
                and _is_partial_refund_echo(reg)):
            logger.info('Partial refund echo ignored for REG-%d (%s of %s returned)',
                        reg.id, reg.refunded_total, reg.payment_amount)
            return _noop('partial refund already recorded')

        if new_status not in ALLOWED_TRANSITIONS.get(reg.payment_status, set()):
            logger.warning(
                'Payment invalid transition %s -> %s for REG-%d',
                reg.payment_status, new_status, reg.id,
            )
            return _noop('no-op transition')

        reg.payment_status = new_status
        if payment_id:
            reg.payment_id = payment_id

        if new_status == 'paid':
            reg.paid_at = datetime.now(timezone.utc)
            reg.status = 'confirmed'
            # Призначити порядковий номер місця per-instance. Робимо до
            # commit, щоб номер опинився в одній транзакції з статусом.
            try:
                from app.services.registration_service import assign_place_number
                assign_place_number(reg)
            except Exception:
                logger.exception(
                    'Failed to assign place_number for REG-%d', reg.id,
                )
                # не блокуючий збій -- статус оновимо, номер можна вручну
        elif new_status == 'refunded':
            reg.status = 'cancelled'
            _fill_full_refund(reg)

        _log_transaction(
            reg_id=reg.id,
            order_id=f'REG-{reg.id}',
            mapped_status=new_status,
            source=source,
            liqpay_status=liqpay_status,
            payment_id=payment_id,
            amount=amount,
            raw_payload=raw_payload,
        )

        try:
            db.session.commit()
            logger.info('Payment REG-%d -> %s', reg.id, new_status)

            # Реферальні бали: нарахувати при 'paid', анулювати при
            # refunded/unpaid. Best-effort -- збій не ламає оплату.
            try:
                from app.services import referral_service
                referral_service.sync_reward_for_registration(reg)
            except Exception:
                logger.exception('Referral reward sync failed for REG-%d', reg.id)

            # Промокод: повернення коштів звільняє використання у ліміті --
            # код можна видати комусь іншому. Знімок знижки на реєстрації
            # лишається (історія платежу не переписується).
            try:
                from app.services import promo_service
                if promo_service.sync_for_registration(reg) is not None:
                    db.session.commit()
            except Exception:
                db.session.rollback()
                logger.exception('Promo sync failed for REG-%d', reg.id)

            if new_status == 'paid':
                from app.services.email_service import EmailService

                # Оплата випередила таймер -- відкладений лист "до оплати"
                # більше не потрібен: payment_confirmed каже все те саме.
                # (Планувальник перевіряє статус і сам, тож збій тут лише
                # лишає зайвий рядок у черзі, а не шле хибний лист.)
                try:
                    if EmailService.cancel_pending_registration_confirmation(reg):
                        db.session.commit()
                except Exception:
                    db.session.rollback()
                    logger.exception(
                        'Failed to cancel pending confirmation for REG-%d', reg.id,
                    )

                try:
                    EmailService.send_payment_confirmation(reg)
                except Exception:
                    logger.exception('Failed to queue payment email for REG-%d', reg.id)

                # Оплата могла прийти, коли місця вже розібрали: місце тримає
                # лише оплачений (services.seating), тож гроші ми не
                # відхиляємо -- сигналимо адміну про перевищення пулу.
                from app.services.seating import notify_overbooking_if_needed
                notify_overbooking_if_needed(reg)

                # Блок 4.1 фаза 2: підтвердження email -- ПІСЛЯ списання
                # коштів. Реєстрація/оплата не гейтяться підтвердженням,
                # тож перший лист з посиланням шлемо оплаченому учаснику.
                try:
                    self._send_email_confirmation_if_needed(reg)
                except Exception:
                    logger.exception(
                        'Failed to queue email-confirmation for REG-%d', reg.id,
                    )

            return True, 'ok'
        except Exception:
            logger.exception('Payment DB error for REG-%d', reg.id)
            return _fail('db error')

    @staticmethod
    def _send_email_confirmation_if_needed(reg):
        """Надіслати лист підтвердження email оплаченому учаснику, якщо
        email ще не підтверджено. url_for може бути недоступний поза
        request-контекстом (status_check зі scheduler-а) -- тоді будуємо
        посилання з SiteSettings.website_url."""
        user = reg.user
        if user is None or user.email_confirmed or not user.email:
            return
        from app.services.email_service import EmailService
        from app.services.token_service import generate_confirmation_token

        token = generate_confirmation_token(user.id)
        try:
            from flask import url_for
            confirm_url = url_for('auth.confirm_email', token=token, _external=True)
        except RuntimeError:
            from app.models.site_settings import SiteSettings
            base = (SiteSettings.get().website_url or '').rstrip('/')
            confirm_url = f'{base}/auth/confirm/{token}'
        EmailService.send_email_confirmation(user, confirm_url)
        logger.info('Email-confirmation queued after payment: REG-%d user=%d',
                    reg.id, user.id)

    def check_enrollment_and_update(self, enrollment):
        """Синхронно перепитати LiqPay про замовлення онлайн-курсу.

        Потрібно для сторінки «оплату отримано»: користувач нерідко
        повертається з LiqPay швидше, ніж приходить серверний callback.
        """
        from app.models.online_enrollment import OnlineEnrollment

        status_data = self.liqpay.check_status(enrollment.order_id)
        if not status_data:
            return False, 'api unavailable'

        lp_status = status_data.get('status', '')
        new_status = STATUS_MAP.get(lp_status)
        if not new_status or new_status == enrollment.payment_status:
            return True, 'no change'

        # populate_existing() тут ОБОВ'ЯЗКОВИЙ, а не гігієнічний. Викликач
        # уже прочитав це замовлення (сторінка успіху, сторінка гостьового
        # замовлення), тож воно лежить в identity map. Без явної вказівки
        # SQLAlchemy віддасть саме той -- старий -- об'єкт, і блокування
        # візьметься на рядок, стан якого ми не побачимо. Наслідок реальний:
        # callback устиг зафіксувати 'paid', ми ще бачимо 'unpaid', перевірка
        # переходу пропускає, і оплата проводиться вдруге -- другий запис у
        # журналі й друга видача доступу, яка гасить щойно надіслане
        # посилання. Той самий висновок описано в certificate_service.
        locked = (
            db.session.query(OnlineEnrollment)
            .with_for_update().populate_existing()
            .filter_by(id=enrollment.id).first()
        )
        if not locked:
            return False, 'enrollment not found'

        return self.update_enrollment_status(
            locked, new_status, str(status_data.get('payment_id', '')),
            amount=status_data.get('amount'), source='status_check',
            liqpay_status=lp_status, raw_payload=status_data,
        )

    def check_and_update(self, reg):
        order_id = f'REG-{reg.id}'
        status_data = self.liqpay.check_status(order_id)
        if not status_data:
            return False, 'api unavailable'

        lp_status = status_data.get('status', '')
        new_status = STATUS_MAP.get(lp_status)
        if not new_status or new_status == reg.payment_status:
            return True, 'no change'

        payment_id = str(status_data.get('payment_id', ''))
        callback_amount = status_data.get('amount')

        locked_reg = (
            db.session.query(EventRegistration)
            .with_for_update().populate_existing()
            .filter_by(id=reg.id).first()
        )
        if not locked_reg:
            return False, 'registration not found'

        return self.update_payment_status(
            locked_reg, new_status, payment_id, amount=callback_amount,
            source='status_check', liqpay_status=lp_status,
            raw_payload=status_data,
        )

    # ---- доплата різниці тарифу (order_id SUR-<transfer_id>) ----

    @staticmethod
    def apply_surcharge(transfer, payment_id, amount):
        """Зарахувати доплату різниці тарифу. Комітить.

        Саме тут payment_amount реєстрації доганяє новий тариф: до цієї
        миті вона лишалась такою, якою людина заплатила спочатку.

        Ідемпотентно за surcharge_paid_at: LiqPay повторює callback, і без
        цієї перевірки різниця додалась би двічі. Викликач (process_callback)
        бере блокування рядка ДО цього виклику -- сама функція чужого
        блокування не ставить, тож прямий виклик поза callback (як у тестах)
        безпечний лише в однопотоковому контексті.

        ВІДОМА ПРОГАЛИНА, залишена свідомо: тут немає перевірки
        reg.status/payment_status. Якщо реєстрацію вже повністю скасували чи
        повернули (initiate_refund) ПІСЛЯ того, як доплату запросили, а
        запізнілий callback прийде вже після цього -- сума все одно
        припишеться до payment_amount скасованого рядка. Свідомо не
        вирішуємо це тут: автоповернення, блокування з позначкою для адміна,
        чи повна відмова прийому -- окреме продуктове рішення власника, не
        архітектурний вибір цього коду. Наразі рядок мовчки розходиться з
        payment_status і чекає на ручну звірку.
        """
        if transfer.surcharge_paid_at is not None:
            logger.info('Surcharge for transfer #%s already applied',
                        transfer.id)
            return False

        reg = transfer.registration
        if reg is None:
            return False

        reg.payment_amount = _money(reg.payment_amount) + _money(amount)
        transfer.surcharge_paid_at = utcnow()
        transfer.surcharge_payment_id = payment_id
        db.session.commit()

        audit_logger.info(
            'Surcharge %s applied to REG-%s via transfer #%s (payment %s)',
            amount, reg.id, transfer.id, payment_id,
        )
        return True

    # ---- повернення коштів ----

    @staticmethod
    def _rescue_refund_record(order, refund_amount, order_id, lp_status,
                              raw_payload, reason):
        """Гроші вже пішли, а транзакція впала: врятувати хоча б слід.

        Найгірший стан у всьому платіжному контурі. Rollback стер щойно
        проставлений `refunded_amount`, і без сліду адмін побачить лише
        «помилка» -- натисне ще раз, і LiqPay проведе ДРУГЕ часткове
        повернення на ту саму суму: підстав відхилити його в нього немає.

        Тому окремою й максимально простою транзакцією пишемо суму та
        рядок журналу. Статус замовлення не чіпаємо: він оживе сам, коли
        прийде callback `reversed` (сума вже дорівнюватиме сплаченій, і
        захист від луни його пропустить).

        Повертаємо ПОМИЛКУ навіть при вдалому рятуванні -- свідомо: стан
        потребує людини, і червоне повідомлення тут доречніше за зелене.
        """
        db.session.rollback()
        is_enrollment = hasattr(order, 'online_course_id')

        try:
            fresh = db.session.get(type(order), order.id)
            if fresh is None:
                raise RuntimeError(f'{order_id} зник після rollback')

            fresh.refunded_amount = fresh.refunded_total + refund_amount
            fresh.refunded_at = datetime.now(timezone.utc)
            _log_transaction(
                reg_id=None if is_enrollment else fresh.id,
                enrollment_id=fresh.id if is_enrollment else None,
                order_id=order_id, mapped_status='paid', source='refund',
                liqpay_status=lp_status, amount=refund_amount,
                raw_payload=raw_payload,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            audit_logger.critical(
                'REFUND NOT RECORDED: LiqPay returned %s UAH for %s, '
                'both the main write (%s) and the rescue write failed. '
                'Reconcile manually against the LiqPay dashboard.',
                refund_amount, order_id, reason,
            )
            logger.exception('Rescue write failed for %s', order_id)
            return False, (
                f'УВАГА: LiqPay повернув {refund_amount} грн, але записати '
                f'операцію не вдалося ({reason}). НЕ повторюйте повернення -- '
                'звірте замовлення з кабінетом LiqPay вручну.'
            )

        audit_logger.error(
            'Refund recorded by rescue write: %s UAH for %s after failure (%s); '
            'payment_status left untouched, needs manual review.',
            refund_amount, order_id, reason,
        )
        return False, (
            f'LiqPay повернув {refund_amount} грн, суму збережено, але статус '
            f'замовлення оновити не вдалося ({reason}). НЕ повторюйте '
            'повернення -- перевірте замовлення вручну.'
        )

    def _record_refund(self, order, refund_amount, reason, admin_user,
                       order_id, lp_status, raw_payload, finalize):
        """Зафіксувати успішне повернення: сума, підстава, статус, лист.

        Тут проходить розвилка, заради якої все й затівалось. ПОВНЕ
        повернення проводиться через update_*_status -- саме там живуть
        наслідки: скасування замовлення, звільнення місця, анулювання
        промокоду й реферальних балів, зняття доступу. ЧАСТКОВЕ не чіпає
        нічого з цього: людина повернула половину грошей за перенесений
        захід, але лишається учасником, і місце за нею зберігається.
        """
        is_enrollment = hasattr(order, 'online_course_id')

        order.refunded_amount = order.refunded_total + refund_amount
        order.refunded_at = datetime.now(timezone.utc)
        if reason:
            order.refund_reason = reason[:500]

        if order.is_fully_refunded:
            ok, msg = finalize()
            if not ok:
                return self._rescue_refund_record(
                    order, refund_amount, order_id, lp_status, raw_payload, msg)
        else:
            _log_transaction(
                reg_id=None if is_enrollment else order.id,
                enrollment_id=order.id if is_enrollment else None,
                order_id=order_id,
                # Часткове повернення лишає замовлення оплаченим, тому й у
                # журналі mapped_status='paid'. Саму операцію видно за
                # source='refund' + amount; окремого статусу свідомо не
                # заводимо, щоб не міняти CHECK на продовій таблиці.
                mapped_status='paid',
                source='refund',
                liqpay_status=lp_status,
                amount=refund_amount,
                raw_payload=raw_payload,
            )
            try:
                db.session.commit()
            except Exception:
                logger.exception('Refund DB error for %s', order_id)
                return self._rescue_refund_record(
                    order, refund_amount, order_id, lp_status, raw_payload,
                    'db error')

        audit_logger.info(
            'Admin %s refunded %s: %s UAH of %s (total returned %s), reason=%s',
            admin_user.email, order_id, refund_amount, order.payment_amount,
            order.refunded_total, reason or '-',
        )

        # Лист -- поза транзакцією й best-effort: гроші вже пішли, і збій
        # пошти не має перетворювати успішне повернення на помилку.
        try:
            from app.services.email_service import EmailService
            EmailService.send_refund_notification(order, refund_amount, reason)
        except Exception:
            logger.exception('Failed to queue refund email for %s', order_id)

        if order.is_fully_refunded:
            return True, f'Повернено повну суму: {refund_amount} грн'
        return True, (f'Повернено {refund_amount} грн '
                      f'(залишок за замовленням: {order.refund_remaining} грн)')

    def initiate_enrollment_refund(self, enrollment, admin_user, amount=None,
                                   reason=None, force=False):
        """Повернути кошти за онлайн-курс через LiqPay.

        `amount is None` -- повернути весь залишок; інакше часткова сума.

        `force` знімає заборону §5.1 (цифровий продукт після надання
        доступу не повертається). Прапорець, а не мовчазний дозвіл: у
        типовому випадку політика має спрацювати сама, а виняток мусить
        бути свідомим рішенням адміна, видимим у логах.

        Замовлення на нуль гривень LiqPay не знає -- його «повернення» це
        лише скасування доступу на нашому боці.
        """
        from app.models.online_enrollment import OnlineEnrollment

        locked = (
            db.session.query(OnlineEnrollment)
            .with_for_update().populate_existing()
            .filter_by(id=enrollment.id).first()
        )
        if not locked or locked.payment_status != 'paid':
            return _fail('Повернення можливе тільки для оплачених замовлень')

        order_id = locked.order_id

        # Безкоштовне замовлення проходить ПЕРЕД перевіркою п. 5.1: там
        # немає грошей, а отже й повернення коштів, яке ця норма забороняє.
        # Скасувати виданий безкоштовно доступ адмін має право завжди.
        if float(locked.payment_amount or 0) <= 0:
            ok, msg = self.update_enrollment_status(
                locked, 'refunded', source='refund',
            )
            if ok:
                audit_logger.info('Admin %s cancelled free %s',
                                  admin_user.email, order_id)
                return True, 'Доступ скасовано (замовлення було безкоштовним)'
            return False, f'Помилка оновлення статусу: {msg}'

        if locked.provisioned_at is not None and not force:
            return _fail(
                'Доступ до матеріалів уже надано -- за політикою 5.1 '
                'повернення за цифровий продукт не здійснюється. '
                'Повернення попри це потребує окремого підтвердження.'
            )

        refund_amount, problem = resolve_refund_amount(locked, amount)
        if problem:
            return _fail(problem)

        result = self.liqpay.create_refund_request(order_id, float(refund_amount))
        if result is None:
            return _fail(LIQPAY_UNREACHABLE)

        lp_status = result.get('status', '')
        if lp_status not in ('reversed', 'sandbox'):
            err = result.get('err_description', result.get('status', 'unknown'))
            logger.warning('LiqPay refund failed %s: %s', order_id, err)
            return _fail(f'LiqPay відхилив повернення: {err}')

        return self._record_refund(
            locked, refund_amount, reason, admin_user, order_id,
            lp_status=lp_status, raw_payload=result,
            finalize=lambda: self.update_enrollment_status(
                locked, 'refunded', source='refund',
                liqpay_status=lp_status, raw_payload=result,
            ),
        )

    def initiate_refund(self, reg, admin_user, amount=None, reason=None):
        """Повернути кошти за реєстрацію на захід через LiqPay.

        `amount is None` -- повернути весь залишок. Часткова сума
        обчислюється не тут: рекомендацію за політикою 4.1 дає
        `services.refund_policy`, а рішення ухвалює адмін у формі. Тут --
        лише перевірка, що сума не більша за залишок, і проведення.
        """
        locked_reg = (
            db.session.query(EventRegistration)
            .with_for_update().populate_existing()
            .filter_by(id=reg.id).first()
        )
        if not locked_reg or locked_reg.payment_status != 'paid':
            return _fail('Повернення можливе тільки для оплачених реєстрацій')

        refund_amount, problem = resolve_refund_amount(locked_reg, amount)
        if problem:
            return _fail(problem)

        order_id = f'REG-{locked_reg.id}'
        result = self.liqpay.create_refund_request(order_id, float(refund_amount))

        if result is None:
            return _fail(LIQPAY_UNREACHABLE)

        lp_status = result.get('status', '')
        if lp_status not in ('reversed', 'sandbox'):
            err = result.get('err_description', result.get('status', 'unknown'))
            logger.warning('LiqPay refund failed REG-%d: %s', locked_reg.id, err)
            return _fail(f'LiqPay відхилив повернення: {err}')

        return self._record_refund(
            locked_reg, refund_amount, reason, admin_user, order_id,
            lp_status=lp_status, raw_payload=result,
            finalize=lambda: self.update_payment_status(
                locked_reg, 'refunded', source='refund',
                liqpay_status=lp_status, raw_payload=result,
            ),
        )


#: Стеля одного прогону звірки. Сьогодні в 'pending' одиниці рядків, тож
#: число ні на що не впливає -- воно стоїть проти майбутнього: звірка живе
#: в HTTP-запиті адмінки, і сотня звернень до чужого API поспіль вичерпала б
#: таймаут gunicorn замість того, щоб чесно сказати, скільки встигла.
RECONCILE_LIMIT = 100


def _check_one(report, order_id, call):
    """Опитати одне замовлення й розкласти результат по кошиках звіту.

    Виняток тут ловиться навмисно, а не спливає вище. Мережа до LiqPay
    падає не лише чемним ``None``: таймаут чи розрив зʼєднання -- це
    виняток, і без цієї ловушки перший же такий рядок перетворював би весь
    прогін на 500, не зробивши нічого для решти.

    Відкат обовʼязковий разом із ловушкою: виняток міг застати
    ``update_payment_status`` посеред транзакції, і брудна сесія отруїла б
    наступне замовлення чужою помилкою.
    """
    try:
        ok, msg = call()
    except Exception as exc:
        db.session.rollback()
        logger.exception('LiqPay reconcile failed for %s', order_id)
        ok, msg = False, str(exc) or exc.__class__.__name__

    if not ok:
        report['failed'] += 1
    elif msg == 'ok':
        report['updated'] += 1
    else:
        report['unchanged'] += 1
    report['details'].append(f'{order_id}: {msg}')


def reconcile_pending(service=None, limit=RECONCILE_LIMIT, max_age_days=None):
    """Перепитати LiqPay про замовлення, що зависли в 'pending'.

    ЩО ЦЕ ЛАГОДИТЬ. `pending` означає, що гроші вже в дорозі: LiqPay
    відповів `processing` або `wait_accept`. Вийти з цього стану замовлення
    може лише двома шляхами, і обидва умовні -- повторний колбек (його бік,
    не наш; загублений ніхто не перезапитує) або `check_and_update` на
    сторінці, куди має зайти сам платник. Якщо не сталося ні того, ні
    іншого, рядок висить вічно, а разом із ним мовчать лист про оплату,
    подія партнеру й вивіз у KeyCRM.

    ЧОМУ ЛИШЕ 'pending'. `unpaid` -- це 900+ рядків, і майже всі вони люди,
    які просто не заплатили. Загублений колбек від «не платив» у даних не
    відрізнити: в обох `payment_id IS NULL`. Мести по них означало б сотні
    звернень до чужого API заради одиниць влучань.

    ВЛАСНОЇ ЛОГІКИ ПЕРЕХОДІВ ТУТ НЕМАЄ -- і це навмисно. Вся вона живе в
    `check_and_update` / `check_enrollment_and_update`: блокування рядка,
    звірка суми, дозволений перехід, журнал транзакції, лист, номер місця,
    подія партнеру. Друга копія поруч розійшлася б із першою при першій же
    правці, і розбіжність жила б саме там, де її найважче помітити.

    Обидва типи замовлень разом: звірка, яка мовчки бачить лише REG-, --
    пастка на день, коли онлайн-курс зависне так само.

    ``max_age_days`` обмежує вибірку свіжими замовленнями; ``None`` --
    без обмеження. Деталі -- у коментарі біля самої умови.

    Повертає звіт ``{'checked', 'updated', 'unchanged', 'failed', 'details',
    'error'}``. Порожній звіт -- не помилка: зависати нема чому.
    """
    from app.models.online_enrollment import OnlineEnrollment

    if service is None:
        from app.services.liqpay import get_liqpay_service
        service = get_liqpay_service()

    report = {'checked': 0, 'updated': 0, 'unchanged': 0, 'failed': 0,
              'details': [], 'error': None}

    if not service.is_configured:
        report['error'] = 'LiqPay не налаштовано -- спочатку збережіть ключі'
        return report

    ops = PaymentOps(service)

    # Вікно за віком -- запобіжник саме для ПЕРІОДИЧНОГО виклику. Замовлення
    # вміє зависнути назавжди: людина ткнула LiqPay, платіж лишився в
    # `wait_accept`, а гроші потім прийшли за рахунком. Такий рядок не
    # зрушить ніколи, і без вікна джоба питала б про нього кожні 15 хвилин
    # роками. `None` -- поведінка кнопки: адмін попросив, дивимось усе.
    since = (datetime.now(timezone.utc) - timedelta(days=max_age_days)
             if max_age_days else None)

    reg_q = (
        db.session.query(EventRegistration)
        .filter(EventRegistration.payment_status == 'pending',
                EventRegistration.payment_amount > 0)
    )
    if since is not None:
        reg_q = reg_q.filter(EventRegistration.created_at >= since)
    regs = reg_q.order_by(EventRegistration.id).limit(limit).all()
    for reg in regs:
        report['checked'] += 1
        _check_one(report, f'REG-{reg.id}',
                   lambda item=reg: ops.check_and_update(item))

    # Залишок ліміту -- онлайн-курсам. Спільна стеля, а не своя на кожен тип:
    # обмежує вона час одного HTTP-запиту, а він у них один на двох.
    rest = limit - len(regs)
    if rest > 0:
        enr_q = (
            db.session.query(OnlineEnrollment)
            .filter(OnlineEnrollment.payment_status == 'pending')
        )
        if since is not None:
            enr_q = enr_q.filter(OnlineEnrollment.created_at >= since)
        enrollments = enr_q.order_by(OnlineEnrollment.id).limit(rest).all()
        for item in enrollments:
            report['checked'] += 1
            _check_one(report, item.order_id,
                       lambda row=item: ops.check_enrollment_and_update(row))

    # Без `details`: у лог іде підсумок, а перелік замовлень адмін бачить
    # на екрані -- дублювати його рядком на кожен прогін немає навіщо.
    #
    # Рівень залежить від того, чи було що робити. Функцію викликає не лише
    # кнопка, а й джоба кожні 15 хвилин, і в звичайний день зависли платежів
    # немає взагалі: INFO «checked: 0» дав би сотню порожніх рядків на добу
    # й навчив читати лог по діагоналі.
    summary = {k: v for k, v in report.items() if k != 'details'}
    log = logger.info if report['checked'] else logger.debug
    log('LiqPay reconcile: %s', summary)
    return report
