"""Адмінка: замовлення онлайн-курсів.

Досі покупки не мали жодного екрана: у списку курсів видно каталог, а хто
й за що заплатив -- ніде. Через це не було й де підтвердити оплату руками,
хоч для реєстрацій на заходи це щоденна операція (людина заплатила на
рахунок, менеджер проставляє «оплачено»).

Зміна статусу йде через той самий PaymentOps, що й LiqPay-callback, а не
присвоєнням поля: там живуть правила переходів, журнал транзакцій і
видача доступу. Присвоєння в обхід означало б, що оплачене вручну
замовлення не відкриває курс.
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import contains_eager, joinedload

from app.admin import _listing, admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.user import User

audit_logger = logging.getLogger('audit')

# Замовлення накопичуються без стелі, тож сторінка мусить різати вибірку.
# Той самий розмір, що в промокодах (`routes_promo_codes.PER_PAGE`).
PER_PAGE = 30

PAYMENT_OPTIONS = [
    ('unpaid', 'Не оплачено'),
    ('pending', 'В обробці'),
    ('paid', 'Оплачено'),
    ('refunded', 'Повернено'),
]

STATUS_OPTIONS = [
    ('pending', 'Очікує'),
    ('active', 'Активне'),
    ('cancelled', 'Скасоване'),
]


def _order_filters():
    return {
        'q': _listing.text_arg('q'),
        'payment': _listing.choice_arg('payment',
                                       [key for key, _ in PAYMENT_OPTIONS]),
        'status': _listing.choice_arg('status',
                                      [key for key, _ in STATUS_OPTIONS]),
    }


def _orders_query(filters):
    """Запит списку. Спільний зі сторінкою й експортом -- інакше файл
    відповідав би на інший зріз, ніж той, що людина бачить на екрані."""
    # contains_eager, а не joinedload: join нижче потрібен для пошуку, і
    # joinedload поверх нього додав би ДРУГУ пару аліасованих LEFT JOIN до
    # тих самих таблиць. promo_code тягнемо окремо -- шаблон читає його код
    # у комірці суми, і без цього кожен рядок зі знижкою коштував би запит.
    query = (
        OnlineEnrollment.query
        .join(User, User.id == OnlineEnrollment.user_id)
        .join(OnlineCourse, OnlineCourse.id == OnlineEnrollment.online_course_id)
        .options(
            contains_eager(OnlineEnrollment.user),
            contains_eager(OnlineEnrollment.course),
            joinedload(OnlineEnrollment.promo_code),
        )
    )
    query = _listing.apply_search(
        query, filters['q'],
        [User.email, User.first_name, User.last_name,
         OnlineCourse.remote_name, OnlineCourse.title],
    )
    if filters['payment']:
        query = query.filter(OnlineEnrollment.payment_status == filters['payment'])
    if filters['status']:
        query = query.filter(OnlineEnrollment.status == filters['status'])

    return query.order_by(OnlineEnrollment.created_at.desc())


@admin_bp.route('/online-orders')
@admin_required
def online_orders_list():
    filters = _order_filters()
    pagination = _orders_query(filters).paginate(
        page=request.args.get('page', 1, type=int),
        per_page=PER_PAGE, error_out=False,
    )
    orders = pagination.items

    # Лічильники рахуємо по ВСІХ замовленнях, а не по зрізу: картка, що
    # змінюється разом із фільтром, відповідає на інше питання, ніж та,
    # заради якої на неї дивляться.
    totals = {
        'all': OnlineEnrollment.query.count(),
        'paid': OnlineEnrollment.query.filter_by(payment_status='paid').count(),
        'unpaid': OnlineEnrollment.query.filter_by(payment_status='unpaid').count(),
        # Оплачено, але доступ не видано -- саме той стан, заради якого
        # сторінка й потрібна найбільше.
        'stuck': OnlineEnrollment.query.filter(
            OnlineEnrollment.payment_status == 'paid',
            OnlineEnrollment.provisioned_at.is_(None),
        ).count(),
    }

    return render_template(
        'admin/online_orders.html',
        orders=orders,
        pagination=pagination,
        filter_args=_listing.filter_args(filters),
        filters=filters,
        payment_options=PAYMENT_OPTIONS,
        status_options=STATUS_OPTIONS,
        totals=totals,
    )


@admin_bp.route('/online-orders/<int:enrollment_id>/payment', methods=['POST'])
@admin_required
def online_order_set_payment(enrollment_id):
    """Ручна зміна статусу оплати.

    Через PaymentOps, а не присвоєнням: там перевірка допустимості
    переходу, журнал транзакцій, видача доступу при 'paid' і зняття
    доступу з анулюванням промокоду при 'refunded'.
    """
    from app.services.liqpay import get_liqpay_service
    from app.services.payment_ops import PaymentOps

    enrollment = db.session.get(OnlineEnrollment, enrollment_id)
    if enrollment is None:
        flash('Замовлення не знайдено', 'error')
        return redirect(url_for('admin.online_orders_list'))

    new_status = request.form.get('payment_status', '')
    if new_status not in [key for key, _ in PAYMENT_OPTIONS]:
        flash('Невідомий статус оплати', 'error')
        return redirect(url_for('admin.online_orders_list'))

    # Блокування рядка -- як у callback: менеджер може натиснути статус тієї
    # ж миті, коли прийде відповідь LiqPay, і без нього обидва переходи
    # прочитали б однаковий стан.
    enrollment = (
        db.session.query(OnlineEnrollment)
        .filter_by(id=enrollment_id)
        .with_for_update()
        .first()
    )
    old_status = enrollment.payment_status
    ops = PaymentOps(get_liqpay_service())
    ok, message = ops.update_enrollment_status(
        enrollment, new_status, amount=enrollment.payment_amount,
        source='manual',
    )

    audit_logger.info(
        'Admin %s set %s payment %s -> %s (%s)',
        current_user.email, enrollment.order_id, old_status, new_status, message,
    )

    if ok and message == 'ok':
        flash(f'Оплату змінено на «{dict(PAYMENT_OPTIONS)[new_status]}»', 'success')
    elif ok:
        # Перехід не відбувся, але це не помилка: наприклад, статус уже той
        # самий. Мовчати не можна -- адмін вирішить, що спрацювало.
        flash('Статус не змінено: такий перехід недопустимий', 'warning')
    else:
        flash(f'Не вдалося змінити статус: {message}', 'error')

    return redirect(url_for('admin.online_orders_list'))


@admin_bp.route('/online-orders/<int:enrollment_id>/reissue', methods=['POST'])
@admin_required
def online_order_reissue(enrollment_id):
    """Перевидати доступ -- для замовлень, що зависли без нього."""
    from app.services import sintegrum_access

    enrollment = db.session.get(OnlineEnrollment, enrollment_id)
    if enrollment is None:
        flash('Замовлення не знайдено', 'error')
        return redirect(url_for('admin.online_orders_list'))

    if not enrollment.is_paid:
        flash('Доступ видається лише для оплачених замовлень', 'error')
        return redirect(url_for('admin.online_orders_list'))

    try:
        sintegrum_access.close_transaction_before_network()
        sintegrum_access.provision_and_notify(enrollment)
    except Exception as exc:
        db.session.rollback()
        flash(f'Не вдалося видати доступ: {exc}', 'error')
        return redirect(url_for('admin.online_orders_list'))

    audit_logger.info('Admin %s reissued access for %s',
                      current_user.email, enrollment.order_id)
    flash('Доступ видано, лист надіслано', 'success')
    return redirect(url_for('admin.online_orders_list'))


@admin_bp.route('/online-orders/<int:enrollment_id>/refund', methods=['POST'])
@admin_required
def online_order_refund(enrollment_id):
    """Повернути кошти через LiqPay.

    Окремо від зміни статусу вручну: там менеджер лише фіксує те, що вже
    сталося поза системою, а тут ми справді просимо LiqPay повернути гроші.
    Плутати ці дві дії не можна -- одна з них рухає гроші.
    """
    from app.services.liqpay import get_liqpay_service
    from app.services.payment_ops import PaymentOps

    enrollment = db.session.get(OnlineEnrollment, enrollment_id)
    if enrollment is None:
        flash('Замовлення не знайдено', 'error')
        return redirect(url_for('admin.online_orders_list'))

    ops = PaymentOps(get_liqpay_service())
    ok, message = ops.initiate_enrollment_refund(enrollment, current_user)
    flash(message, 'success' if ok else 'error')
    return redirect(url_for('admin.online_orders_list'))


@admin_bp.route('/online-orders/export')
@admin_required
def online_orders_export():
    """Вивантажити поточний зріз замовлень у xlsx.

    Тут гроші: суми, знижки, статуси оплат. Досі звірити їх можна було лише
    очима по екрану, тоді як для промокодів і проведень експорт є давно.
    """
    from app.services import xlsx_reports

    filters = _order_filters()
    orders = _orders_query(filters).all()
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Оплата', dict(PAYMENT_OPTIONS).get(filters['payment'], 'Будь-яка')),
            ('Стан', dict(STATUS_OPTIONS).get(filters['status'], 'Будь-який')),
        ],
        len(orders),
    )
    audit_logger.info(
        'Admin %s exported online orders xlsx (%d rows, filters=%s)',
        current_user.email, len(orders), filters,
    )
    return _listing.xlsx_export(
        orders, 'online-orders',
        lambda: xlsx_reports.export_online_orders_xlsx(
            orders, applied_filters=summary),
        'admin.online_orders_list', **_listing.filter_args(filters),
    )
