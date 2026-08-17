"""
DB-aware payment operations.

Single code path for all payment status transitions.
Uses row-level locking to prevent race conditions.
"""
import logging
from datetime import datetime, timezone

from app.extensions import db
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


def parse_order_id(order_id):
    """Розібрати order_id у пару (тип, числовий id).

    Типи: 'registration' (REG-<id>) і 'enrollment' (ONL-<id>).
    Повертає (None, None) для невідомого чи побитого формату.
    """
    for prefix, kind in (('REG-', 'registration'), ('ONL-', 'enrollment')):
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

        reg_id = object_id
        reg = db.session.query(EventRegistration).with_for_update().filter_by(
            id=reg_id
        ).first()
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

        enrollment = db.session.query(OnlineEnrollment).with_for_update().filter_by(
            id=enrollment_id
        ).first()
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

        locked = db.session.query(OnlineEnrollment).with_for_update().filter_by(
            id=enrollment.id
        ).first()
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

        locked_reg = db.session.query(EventRegistration).with_for_update().filter_by(
            id=reg.id
        ).first()
        if not locked_reg:
            return False, 'registration not found'

        return self.update_payment_status(
            locked_reg, new_status, payment_id, amount=callback_amount,
            source='status_check', liqpay_status=lp_status,
            raw_payload=status_data,
        )

    def initiate_enrollment_refund(self, enrollment, admin_user):
        """Повернути кошти за онлайн-курс через LiqPay.

        Дзеркало `initiate_refund` для другого типу замовлень. Статус
        міняється не присвоєнням, а тим самим `update_enrollment_status`:
        там і журнал транзакцій, і зняття доступу, і анулювання промокоду.

        Замовлення на нуль гривень LiqPay не знає -- його «повернення» це
        лише скасування доступу на нашому боці.
        """
        from app.models.online_enrollment import OnlineEnrollment

        locked = db.session.query(OnlineEnrollment).with_for_update().filter_by(
            id=enrollment.id
        ).first()
        if not locked or locked.payment_status != 'paid':
            return _fail('Повернення можливе тільки для оплачених замовлень')

        amount = float(locked.payment_amount or 0)
        order_id = locked.order_id

        if amount <= 0:
            ok, msg = self.update_enrollment_status(
                locked, 'refunded', source='refund',
            )
            if ok:
                audit_logger.info('Admin %s cancelled free %s',
                                  admin_user.email, order_id)
                return True, 'Доступ скасовано (замовлення було безкоштовним)'
            return False, f'Помилка оновлення статусу: {msg}'

        result = self.liqpay.create_refund_request(order_id, amount)
        if result is None:
            return _fail('Не вдалося зв\'єднатися з LiqPay API')

        lp_status = result.get('status', '')
        if lp_status in ('reversed', 'sandbox'):
            ok, msg = self.update_enrollment_status(
                locked, 'refunded', source='refund',
                liqpay_status=lp_status, raw_payload=result,
            )
            if ok:
                audit_logger.info('Admin %s refunded %s (%s UAH)',
                                  admin_user.email, order_id, amount)
                return True, f'Повернення коштів ініційовано: {amount} UAH'
            return False, f'Помилка оновлення статусу: {msg}'

        err = result.get('err_description', result.get('status', 'unknown'))
        logger.warning('LiqPay refund failed %s: %s', order_id, err)
        return _fail(f'LiqPay відхилив повернення: {err}')

    def initiate_refund(self, reg, admin_user):
        locked_reg = db.session.query(EventRegistration).with_for_update().filter_by(
            id=reg.id
        ).first()
        if not locked_reg or locked_reg.payment_status != 'paid':
            return _fail('Повернення можливе тільки для оплачених реєстрацій')

        order_id = f'REG-{locked_reg.id}'
        result = self.liqpay.create_refund_request(order_id, float(locked_reg.payment_amount))

        if result is None:
            return _fail('Не вдалося зв\'єднатися з LiqPay API')

        lp_status = result.get('status', '')
        if lp_status in ('reversed', 'sandbox'):
            ok, msg = self.update_payment_status(
                locked_reg, 'refunded',
                source='refund', liqpay_status=lp_status,
                raw_payload=result,
            )
            if ok:
                audit_logger.info(
                    'Admin %s refunded REG-%d (%s UAH)',
                    admin_user.email, locked_reg.id, locked_reg.payment_amount,
                )
                return True, f'Повернення коштів ініційовано: {locked_reg.payment_amount} UAH'
            return False, f'Помилка оновлення статусу: {msg}'

        err = result.get('err_description', result.get('status', 'unknown'))
        logger.warning('LiqPay refund failed REG-%d: %s', locked_reg.id, err)
        return _fail(f'LiqPay відхилив повернення: {err}')
