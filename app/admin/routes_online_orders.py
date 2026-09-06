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

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import contains_eager, joinedload

from app.admin import _listing, admin_bp
from app.rbac import permission_required
from app.extensions import db
from app.models.mixins import utcnow
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.user import User
from app.utils import ensure_utc


def _wants_json():
    """Клієнт очікує JSON (inline-AJAX), а не redirect (noscript-форма).

    Той самий контракт, що в routes_instances: спільний
    admin-status-select.js шле X-Requested-With і Accept: application/json.
    """
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.accept_mimetypes
    return accept.best_match(['application/json', 'text/html']) == 'application/json'


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

# Стан доступу -- окремий зріз від статусу оплати. Заради `stuck` сторінка
# здебільшого й відкривається: людина заплатила і нічого не отримала.
ACCESS_OPTIONS = [
    ('stuck', 'Оплачено без доступу'),
    ('granted', 'Доступ видано'),
]


def _course_options():
    """Курси, за якими є хоч одне замовлення.

    Не весь каталог: у селекті з десятками треків більшість позицій нічого
    не відфільтрувала б, а порожній результат читається як поламаний
    фільтр. Назва -- наша, інакше з Sintegrum (те саме, що `effective_title`
    дає в адмінці, де мова завжди українська).
    """
    rows = (
        db.session.query(OnlineCourse.id, OnlineCourse.title,
                         OnlineCourse.remote_name)
        .join(OnlineEnrollment,
              OnlineEnrollment.online_course_id == OnlineCourse.id)
        .distinct()
        .order_by(OnlineCourse.remote_name)
        .all()
    )
    return [(str(course_id), title or remote_name)
            for course_id, title, remote_name in rows]


def _order_filters(course_keys=()):
    return {
        'q': _listing.text_arg('q'),
        'payment': _listing.choice_arg('payment',
                                       [key for key, _ in PAYMENT_OPTIONS]),
        'status': _listing.choice_arg('status',
                                      [key for key, _ in STATUS_OPTIONS]),
        'access': _listing.choice_arg('access',
                                      [key for key, _ in ACCESS_OPTIONS]),
        'course': _listing.choice_arg('course', list(course_keys)),
        # Гроші звіряють за період -- як у реєстраціях, сертифікатах і
        # заявках на повернення. Межі рахуються київською добою
        # (_listing.apply_date_range), бо саме нею закривають місяць.
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
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
    if filters['course']:
        query = query.filter(
            OnlineEnrollment.online_course_id == int(filters['course']))
    query = _listing.apply_date_range(
        query, OnlineEnrollment.created_at,
        filters['date_from'], filters['date_to'],
    )
    if filters['access'] == 'stuck':
        query = query.filter(
            OnlineEnrollment.payment_status == 'paid',
            OnlineEnrollment.provisioned_at.is_(None),
        )
    elif filters['access'] == 'granted':
        query = query.filter(OnlineEnrollment.provisioned_at.isnot(None))

    return query.order_by(OnlineEnrollment.created_at.desc())


def _waiting_hours(orders):
    """Скільки годин оплачене замовлення чекає на доступ.

    Рахуємо тут, а не в шаблоні: різниця дат потребує ensure_utc (SQLite
    віддає naive), а це правило має жити в одному місці.
    """
    now = utcnow()
    waiting = {}
    for order in orders:
        if not order.is_paid or order.provisioned_at is not None:
            continue
        since = ensure_utc(order.paid_at or order.created_at)
        if since is None:
            continue
        waiting[order.id] = int((now - since).total_seconds() // 3600)
    return waiting


@admin_bp.route('/online-orders')
@permission_required('online_orders.view')
def online_orders_list():
    course_options = _course_options()
    filters = _order_filters([key for key, _ in course_options])
    pagination = _orders_query(filters).paginate(
        page=_listing.page_arg(),
        per_page=PER_PAGE, error_out=False,
    )
    orders = pagination.items

    # Лічильники рахуємо по ВСІХ замовленнях, а не по зрізу: картка, що
    # змінюється разом із фільтром, відповідає на інше питання, ніж та,
    # заради якої на неї дивляться.
    # Один прохід замість чотирьох COUNT(*) по тій самій таблиці: замовлення
    # накопичуються без стелі, і чотири окремі запити читали її чотири рази.
    # `count(case(...))` рахує лише непорожні значення, тож працює і на SQLite.
    counted = db.session.query(
        db.func.count(OnlineEnrollment.id),
        db.func.count(db.case(
            (OnlineEnrollment.payment_status == 'paid', 1))),
        db.func.count(db.case(
            (OnlineEnrollment.payment_status == 'unpaid', 1))),
        # Оплачено, але доступ не видано -- саме той стан, заради якого
        # сторінка й потрібна найбільше.
        db.func.count(db.case((db.and_(
            OnlineEnrollment.payment_status == 'paid',
            OnlineEnrollment.provisioned_at.is_(None)), 1))),
    ).one()
    totals = {
        'all': counted[0],
        'paid': counted[1],
        'unpaid': counted[2],
        'stuck': counted[3],
    }

    return render_template(
        'admin/online_orders.html',
        orders=orders,
        pagination=pagination,
        filter_args=_listing.filter_args(filters),
        filters=filters,
        payment_options=PAYMENT_OPTIONS,
        status_options=STATUS_OPTIONS,
        access_options=ACCESS_OPTIONS,
        course_options=course_options,
        totals=totals,
        waiting_hours=_waiting_hours(orders),
    )


@admin_bp.route('/online-orders/<int:enrollment_id>/payment', methods=['POST'])
@permission_required('online_orders.manage')
def online_order_set_payment(enrollment_id):
    """Ручна зміна статусу оплати.

    Через PaymentOps, а не присвоєнням: там перевірка допустимості
    переходу, журнал транзакцій, видача доступу при 'paid' і зняття
    доступу з анулюванням промокоду при 'refunded'.
    """
    from app.services.liqpay import get_liqpay_service
    from app.services.payment_ops import PaymentOps

    # `status` -- поле спільного admin-status-select.js, `payment_status` --
    # історична назва з noscript-форми. Приймаємо обидва: інакше сторінка
    # працювала б або з JS, або без нього.
    wants_json = _wants_json()
    new_status = (request.form.get('status')
                  or request.form.get('payment_status') or '').strip()
    if new_status not in [key for key, _ in PAYMENT_OPTIONS]:
        if wants_json:
            return jsonify({'ok': False, 'error': 'Невідомий статус оплати'}), 400
        flash('Невідомий статус оплати', 'error')
        return redirect(url_for('admin.online_orders_list'))

    # Одразу під блокуванням, без попереднього читання: менеджер може
    # натиснути статус тієї ж миті, коли прийде відповідь LiqPay, і обидва
    # переходи прочитали б однаковий стан. populate_existing() -- щоб
    # блокування давало ще й свіжі дані, а не об'єкт з identity map.
    enrollment = (
        db.session.query(OnlineEnrollment)
        .with_for_update().populate_existing()
        .filter_by(id=enrollment_id)
        .first()
    )
    if enrollment is None:
        if wants_json:
            return jsonify({'ok': False, 'error': 'Замовлення не знайдено'}), 404
        flash('Замовлення не знайдено', 'error')
        return redirect(url_for('admin.online_orders_list'))

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

    labels = dict(PAYMENT_OPTIONS)
    if ok and message == 'ok':
        if wants_json:
            return jsonify({'ok': True, 'status': enrollment.payment_status,
                            'status_label': labels[enrollment.payment_status]})
        flash(f'Оплату змінено на «{labels[new_status]}»', 'success')
    elif ok:
        # Перехід не відбувся, але це не помилка: наприклад, статус уже той
        # самий. Мовчати не можна -- адмін вирішить, що спрацювало.
        if wants_json:
            return jsonify({'ok': False,
                            'error': 'Такий перехід недопустимий'}), 400
        flash('Статус не змінено: такий перехід недопустимий', 'warning')
    else:
        if wants_json:
            return jsonify({'ok': False, 'error': message}), 400
        flash(f'Не вдалося змінити статус: {message}', 'error')

    return redirect(url_for('admin.online_orders_list'))


@admin_bp.route('/online-orders/<int:enrollment_id>/reissue', methods=['POST'])
@permission_required('online_orders.manage')
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


@admin_bp.route('/online-orders/<int:enrollment_id>/login-link', methods=['POST'])
@permission_required('online_orders.manage')
def online_order_login_link(enrollment_id):
    """Передати покупцю посилання на встановлення пароля.

    Єдиний ручний крок у всьому ланцюжку: API партнера не вміє ані видати
    пароль новому учню, ані надіслати запрошення. Адмін бере персональне
    посилання в кабінеті Sintegrum, вставляє сюди -- і система надсилає
    його покупцю сама, замість листування вручну.
    """
    from app.admin._helpers import try_commit
    from app.models.mixins import utcnow
    from app.services.email_service import EmailService

    enrollment = db.session.get(OnlineEnrollment, enrollment_id)
    if enrollment is None:
        flash('Замовлення не знайдено', 'error')
        return redirect(url_for('admin.online_orders_list'))

    link = (request.form.get('login_link') or '').strip()
    if not link.startswith('https://'):
        flash('Посилання на встановлення пароля має починатися з https://',
              'error')
        return redirect(url_for('admin.online_orders_list'))
    if len(link) > 500:
        flash('Посилання задовге', 'error')
        return redirect(url_for('admin.online_orders_list'))

    enrollment.login_link = link
    enrollment.login_link_sent_at = utcnow()
    if not try_commit(log_context=f'login link for {enrollment.order_id}'):
        return redirect(url_for('admin.online_orders_list'))

    if EmailService.send_online_login_link(enrollment) is None:
        flash('Посилання збережено, але лист не пішов -- перевірте пошту в логах',
              'warning')
    else:
        flash('Посилання надіслано покупцю', 'success')

    audit_logger.info('Admin %s sent login link for %s',
                      current_user.email, enrollment.order_id)
    return redirect(url_for('admin.online_orders_list'))


@admin_bp.route('/online-orders/export')
@permission_required('online_orders.export')
def online_orders_export():
    """Вивантажити поточний зріз замовлень у xlsx.

    Тут гроші: суми, знижки, статуси оплат. Досі звірити їх можна було лише
    очима по екрану, тоді як для промокодів і проведень експорт є давно.
    """
    from app.services import xlsx_reports

    course_options = _course_options()
    filters = _order_filters([key for key, _ in course_options])
    # Стелю рядків міряємо COUNT-ом ДО вибірки: інакше зріз спершу
    # піднімався б у пам'ять цілком і лише потім отримував відмову.
    orders, refusal = _listing.export_query(
        _orders_query(filters), 'admin.online_orders_list', **_listing.filter_args(filters),
    )
    if refusal:
        return refusal
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Оплата', dict(PAYMENT_OPTIONS).get(filters['payment'], 'Будь-яка')),
            ('Стан', dict(STATUS_OPTIONS).get(filters['status'], 'Будь-який')),
            ('Доступ', dict(ACCESS_OPTIONS).get(filters['access'], 'Будь-який')),
            ('Курс', dict(course_options).get(filters['course'], 'Усі')),
            ('Період', _listing.date_range_label(filters, empty='Увесь')),
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
