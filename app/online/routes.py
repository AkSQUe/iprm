"""Публічний каталог онлайн-курсів.

Окремий розділ від /courses: там офлайн-заходи з датами, містами й місцями,
тут -- навчання, що йде в Sintegrum і не має ані дати, ані обмеження місць.

Читаємо ТІЛЬКИ дзеркало в нашій базі. Жодного звернення до Sintegrum на
рендері: недоступність чужого API не повинна робити розділ порожнім.

access_url у публічні шаблони не передається ніколи -- це фактично ключ від
навчання. Учасник отримує його лише через наш токен-редірект після оплати.
"""
import io
import logging

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db, limiter
from app.models.online_course import OnlineCourse
from app.models.online_enrollment import OnlineEnrollment
from app.models.site_settings import SiteSettings
from app.online import online_bp
from app.online.forms import OnlineBuyerForm
from app.services.recaptcha import verify_request as verify_recaptcha

logger = logging.getLogger(__name__)


def _published_query():
    """Опубліковані курси з підвантаженою обкладинкою.

    `card_media` читає кожна картка каталогу, тож без selectinload список
    коштував би запит на курс. Офлайн-каталог робить так само
    (`course_listing.gather_active_courses`).
    """
    return OnlineCourse.query.options(
        selectinload(OnlineCourse.card_media),
    ).filter(
        OnlineCourse.is_published.is_(True),
        OnlineCourse.is_vanished.is_(False),
    )


@online_bp.route('/')
def course_list():
    courses = _published_query().order_by(
        OnlineCourse.is_featured.desc(),
        OnlineCourse.sort_order,
        OnlineCourse.remote_name,
    ).all()

    return render_template(
        'online/list.html',
        active_nav='online',
        courses=courses,
    )


@online_bp.route('/<slug>')
def course_detail(slug):
    course = _published_query().filter_by(slug=slug).first()
    if not course:
        # Неопублікований або зниклий курс не існує для публіки -- саме 404,
        # а не 403: інакше сторінка підтверджувала б, що такий курс у нас є.
        abort(404)

    related = [
        item for item in _published_query().order_by(
            OnlineCourse.is_featured.desc(), OnlineCourse.sort_order,
        ).limit(4).all()
        if item.id != course.id
    ][:3]

    existing = None
    if current_user.is_authenticated:
        existing = _live_enrollment(current_user.id, course.id)

    # Опубліковані відгуки саме про цей онлайн-курс. Прив'язка з'явилась
    # разом із поліморфним online_course_id (див. плани редизайну).
    from app.models.review import Review
    course_reviews = Review.alive().filter_by(
        online_course_id=course.id, is_published=True,
    ).order_by(Review.sort_order, Review.created_at.desc()).limit(6).all()

    gallery = course.gallery

    # Якорі секцій для глобальної шапки -- у порядку самих секцій. #buy
    # живе всередині секції #about, тож іде одразу за нею.
    anchors = []
    if course.t('benefits'):
        anchors.append(('benefits', _('Результат')))
    # Калькулятор окупності. Умова дзеркалить шаблон: він малюється лише за
    # увімкненого налаштування, з ціною і тільки в гривні (суми підписані ₴).
    settings = SiteSettings.get()
    if (settings.show_roi_calculator and course.currency == 'UAH'
            and course.effective_price and course.effective_price > 0):
        anchors.append(('roi', _('Окупність')))
    anchors.append(('about', _('Про курс')))
    anchors.append(('buy', _('Вартість')))
    if gallery:
        anchors.append(('gallery', _('Як проходить')))
    if course.program_blocks or course.t('practice_note_title'):
        anchors.append(('program', _('Програма')))
    if course.trainer:
        anchors.append(('trainer', _('Тренер')))
    if course_reviews:
        anchors.append(('reviews', _('Відгуки')))
    if course.faq:
        anchors.append(('faq', _('Питання')))

    if existing and existing.is_paid:
        cta = {'href': url_for('auth.account'), 'label': _('Перейти до навчання')}
    elif course.is_purchasable:
        cta = {'href': url_for('online.checkout', slug=course.slug),
               'label': _('Купити курс')}
    else:
        cta = {'href': url_for('main.contact'), 'label': _('Запитати про курс')}

    return render_template(
        'online/detail.html',
        active_nav='online',
        course=course,
        page_anchors=anchors,
        # Місць в онлайн-курсі не буває -- лічильник у шапці не показуємо.
        page_anchor_seats=None,
        page_anchor_cta=cta,
        related=related,
        checkout_available=course.is_purchasable,
        existing_enrollment=existing,
        # Галерея -- окремий запит до медіа-реєстру (прив'язка поліморфна).
        gallery=gallery,
        course_reviews=course_reviews,
    )


def _live_enrollment(user_id, course_id):
    """Нескасоване замовлення цього користувача на цей курс."""
    return OnlineEnrollment.query.filter(
        OnlineEnrollment.user_id == user_id,
        OnlineEnrollment.online_course_id == course_id,
        OnlineEnrollment.status != 'cancelled',
    ).first()


@online_bp.route('/<slug>/checkout', methods=['GET', 'POST'])
# 60, а не 20: після переходу на PRG кожна дія з промокодом коштує два
# запити (POST + GET), і людина, яка спробувала кілька кодів і перечитала
# сторінку, впиралась у ліміт на власній покупці. Для перебору кодів 60
# спроб на годину однаково не дають нічого.
@limiter.limit('60 per hour')
def checkout(slug):
    """Оформлення покупки: створює замовлення і віддає форму LiqPay.

    Логін НЕ обов'язковий (рішення 17.08.2026, скасовує Q5). Вимога завести
    акаунт стояла рівно між готовністю платити й оплатою -- у заходів той
    самий бар'єр прибрали 31.07.2026, і онлайн-курси просто лишились на
    старому рішенні. Гість вводить контакти тут-таки, а кабінет заводить
    після оплати, коли гроші вже пройшли.
    """
    course = _published_query().filter_by(slug=slug).first()
    if not course:
        abort(404)

    if not course.is_purchasable:
        flash(_('Цей курс поки не можна купити'), 'error')
        return redirect(url_for('online.course_detail', slug=course.slug))

    if not current_user.is_authenticated:
        return _guest_checkout(course)

    enrollment = _live_enrollment(current_user.id, course.id)

    if enrollment and enrollment.is_paid:
        flash(_('Ви вже придбали цей курс'), 'info')
        return redirect(url_for('auth.account'))

    if enrollment is None:
        # Сума фіксується тут і надалі не перераховується: зміна ціни на
        # сайті не має чіпати вже оформлене замовлення.
        enrollment = OnlineEnrollment(
            user_id=current_user.id,
            online_course_id=course.id,
            payment_amount=course.effective_price,
            payment_status='unpaid',
            status='pending',
        )
        db.session.add(enrollment)
        try:
            db.session.commit()
        except Exception:
            # Найімовірніше -- гонка двох вкладок і частковий унікальний
            # індекс. Тоді замовлення вже існує, ним і користуємось.
            db.session.rollback()
            logger.exception('Failed to create enrollment for course %s', course.id)
            enrollment = _live_enrollment(current_user.id, course.id)
            if enrollment is None:
                flash(_('Не вдалося оформити замовлення. Спробуйте ще раз.'), 'error')
                return redirect(url_for('online.course_detail', slug=course.slug))

    if request.method == 'POST':
        _handle_promo(enrollment, course)
        # Post/Redirect/Get: без нього F5 на сторінці повторно надсилає
        # промокод, а браузер ще й питає про це діалогом.
        return redirect(url_for('online.checkout', slug=course.slug))

    # Знижка 100% робить суму нульовою -- платити нічого, але й форми LiqPay
    # не буде. Без цієї гілки замовлення лишалось би `unpaid` назавжди, а
    # людина -- без доступу до курсу, за який усе вже сплачено кодом.
    if enrollment.payment_amount is not None and enrollment.payment_amount <= 0:
        return _complete_free_order(enrollment, course)

    return render_template(
        'online/checkout.html', **_order_context(enrollment, course))


def _guest_checkout(course):
    """Покупка без акаунта: збираємо контакти й заводимо замовлення.

    Користувача створює `participant_service.resolve_user` -- безпарольного,
    як це вже роблять гостьова реєстрація на захід і адмінські імпорти.
    Пароль людина ставить після оплати, коли решта даних уже зібрана.
    """
    from app.services import participant_service

    form = OnlineBuyerForm()

    def _render():
        return render_template(
            'online/buyer.html', active_nav='online', course=course, form=form)

    if not form.validate_on_submit():
        return _render()

    if not verify_recaptcha(action='online_checkout'):
        flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
        return _render()

    try:
        buyer, is_new_user = participant_service.resolve_user(
            form.email.data, form.phone.data,
        )

        # Адреса вже належить акаунту, який цей курс купує або купив.
        # Другого замовлення не заводимо: часткова унікальність усе одно не
        # дала б, та й платити двічі за той самий курс нема за що.
        if _live_enrollment(buyer.id, course.id) is not None:
            db.session.rollback()
            flash(_('На цю адресу вже є замовлення цього курсу. '
                    'Увійдіть, щоб його побачити.'), 'info')
            return redirect(url_for(
                'auth.login', next=url_for('online.checkout', slug=course.slug)))

        _apply_buyer_data(buyer, form, is_new_user)

        enrollment = OnlineEnrollment(
            user_id=buyer.id,
            online_course_id=course.id,
            payment_amount=course.effective_price,
            payment_status='unpaid',
            status='pending',
        )
        db.session.add(enrollment)
        # Токен видаємо одразу: без нього гість не має жодного способу
        # повернутись до власного замовлення.
        enrollment.issue_order_token()
        db.session.commit()
    except IntegrityError:
        # Гонка двох вкладок або подвійний сабміт: конфлікт можливий на
        # users.email і на частковій унікальності замовлення, і в обох
        # випадках потрібне вже існує. На токен переможця НЕ пускаємо --
        # інакше вгадана чужа адреса відкривала б чуже замовлення.
        db.session.rollback()
        logger.info('Guest checkout race for course %s', course.id)
        flash(_('Замовлення вже оформлюється. Увійдіть, щоб його побачити.'),
              'info')
        return redirect(url_for(
            'auth.login', next=url_for('online.checkout', slug=course.slug)))
    except Exception:
        db.session.rollback()
        logger.exception('Guest checkout failed for course %s', course.id)
        flash(_('Не вдалося оформити замовлення. Спробуйте ще раз.'), 'error')
        return _render()

    logger.info('Guest checkout created %s for user %d (new=%s)',
                enrollment.order_id, buyer.id, is_new_user)
    return redirect(url_for('online.order', token=enrollment.order_token))


def _apply_buyer_data(user, form, is_new_user):
    """ПІБ і телефон покупця.

    Наявному акаунту заповнюємо лише порожні поля: людина, яка колись
    зареєструвалась під своїм ПІБ, не має його втратити через те, що хтось
    (чи вона сама поспіхом) інакше набрав прізвище на чекауті.
    """
    from app.models.medical_profile import MedicalProfile

    if is_new_user or not (user.last_name or '').strip():
        user.last_name = form.last_name.data.strip()
    if is_new_user or not (user.first_name or '').strip():
        user.first_name = form.first_name.data.strip()

    phone = (form.phone.data or '').strip()
    if not phone:
        return

    profile = user.medical_profile
    if profile is None:
        profile = MedicalProfile(
            user_id=user.id, source=MedicalProfile.SOURCE_IMPORTED)
        db.session.add(profile)
        user.medical_profile = profile
    if is_new_user or not (profile.phone or '').strip():
        profile.phone = phone


def _order_context(enrollment, course, token=None):
    """Контекст сторінки замовлення -- спільний для гостя й залогіненого.

    Різниця між ними лише в адресах: гість усюди ходить із токеном, бо
    входу ще не має. Тому маршрути тут -- параметр, а не хардкод у шаблоні.
    """
    return dict(
        active_nav='online',
        course=course,
        enrollment=enrollment,
        # Сума до знижки -- щоб підсумок у картці показував, від чого саме
        # відняли промокод. Рахуємо тут, а не в шаблоні: правило «база =
        # payment_amount + discount_amount» одне на весь модуль.
        base_amount=_order_base_amount(enrollment, course),
        form_action=(url_for('online.order', token=token) if token
                     else url_for('online.checkout', slug=course.slug)),
        invoice_url=(url_for('online.order_invoice_token', token=token) if token
                     else url_for('online.order_invoice',
                                  enrollment_id=enrollment.id)),
        access_href=_access_href(enrollment, token),
        # Токен доступу живе годинами, сторінка замовлення -- тижнями. Тож
        # тут цілком звична ситуація: оплачено, доступ був, посилання
        # протермінувалось. Кнопка перевипуску має бути на місці.
        reissue_url=(url_for('online.order_reissue', token=token)
                     if token and enrollment.is_paid else None),
        access_expired=bool(enrollment.is_paid and enrollment.access_is_expired),
        # Кабінет заводиться тут-таки, після оплати: решта даних уже зібрана
        # покупкою, лишається пароль. Якщо пароль уже є (email виявився
        # наявним акаунтом) -- пропонуємо вхід, а не створення.
        can_set_password=bool(
            token and enrollment.user and not enrollment.user.has_password),
        set_password_url=(url_for('online.order_set_password', token=token)
                          if token else None),
        **_liqpay_context(enrollment, course, token=token),
    )


def _access_href(enrollment, token):
    """Куди веде кнопка «Перейти до навчання» після оплати.

    Гостя -- одразу за токеном доступу: кабінет вимагав би пароля, якого в
    нього ще немає. Поки доступ не видано (провізія падає в чергу джоби),
    кнопки немає взагалі -- вести в нікуди гірше, ніж не вести.
    """
    if not enrollment.is_paid:
        return None
    if token:
        if not enrollment.access_token:
            return None
        return url_for('online.access', token=enrollment.access_token)
    return url_for('auth.account')


def _complete_free_order(enrollment, course, token=None):
    """Закрити замовлення на нуль гривень і відкрити доступ.

    Через PaymentOps, а не присвоєнням статусу: там правила переходів,
    журнал транзакцій і видача доступу. Присвоєння в обхід дало б
    «оплачене» замовлення без курсу.
    """
    from app.services.liqpay import get_liqpay_service
    from app.services.payment_ops import PaymentOps

    ops = PaymentOps(get_liqpay_service())
    ok, message = ops.update_enrollment_status(
        enrollment, 'paid', amount=enrollment.payment_amount, source='manual',
    )
    if not ok:
        logger.error('Failed to close free order %s: %s',
                     enrollment.order_id, message)
        flash(_('Не вдалося оформити безкоштовний доступ. Напишіть нам.'),
              'error')
        return redirect(url_for('online.course_detail', slug=course.slug))

    # Гість на payments.success не потрапить -- той роут вимагає логіну.
    if token:
        return redirect(url_for('online.order', token=token))
    return redirect(url_for('payments.success', order_id=enrollment.order_id))


def _order_base_amount(enrollment, course):
    """Сума замовлення ДО знижки.

    Береться з самого замовлення (`payment_amount` + застосована знижка), а
    не з поточної ціни курсу. Інакше застосування чи зняття промокоду
    перераховувало б замовлення за новою ціною -- а вона могла змінитись і
    в адмінці, і черговою синхронізацією з Sintegrum. Обіцянка «сума
    фіксується в момент оформлення» має триматись і тут.
    """
    if enrollment.payment_amount is None:
        return course.effective_price
    return enrollment.payment_amount + (enrollment.discount_amount or 0)


def _handle_promo(enrollment, course):
    """Застосувати або зняти промокод. Повідомлення -- через flash.

    Знижка рахується від суми ЗАМОВЛЕННЯ до знижки, а не від поточної ціни
    курсу: інакше кожне натискання перераховувало б замовлення за ціною, що
    могла змінитись після його оформлення.
    """
    from app.services import promo_service
    from app.services.promo_service import PromoError

    if enrollment.is_paid:
        return

    base = _order_base_amount(enrollment, course)

    if request.form.get('remove_promo'):
        try:
            promo_service.detach_from_enrollment(enrollment)
            enrollment.payment_amount = base
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Failed to detach promo from %s',
                             enrollment.order_id)
            flash(_('Не вдалося зняти промокод. Спробуйте ще раз.'), 'error')
            return
        flash(_('Промокод знято'), 'info')
        return

    raw = (request.form.get('promo_code') or '').strip()
    if not raw:
        return

    try:
        # user_id тут НЕ передаємо: validate перевірив би ліміт «на одну
        # людину» без винятку для цього ж замовлення, і повторне
        # застосування того самого коду падало б з «ви вже використали».
        promo, _discount, _final = promo_service.validate_for_online(
            raw, amount=base,
        )
        # Саме enrollment.user_id, а не current_user: у гостьовому флоу
        # покупець не залогінений, але користувач у замовлення вже є.
        promo_service.assert_user_limit(
            promo, enrollment.user_id, ignore_enrollment_id=enrollment.id,
        )
        promo_service.apply_to_enrollment(promo, enrollment, base)
        db.session.commit()
    except PromoError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return
    except Exception:
        db.session.rollback()
        logger.exception('Failed to apply promo to %s', enrollment.order_id)
        flash(_('Не вдалося застосувати промокод. Спробуйте ще раз.'), 'error')
        return

    flash(_('Промокод застосовано'), 'success')


def _liqpay_context(enrollment, course, token=None):
    """Дані форми LiqPay. Порожньо, якщо платіжку не налаштовано."""
    from app.services.liqpay import get_liqpay_service

    service = get_liqpay_service()
    # Оплачене замовлення форми не потребує: шаблон її не показує, а
    # підписаний платіжний пакет на вже сплачену суму краще й не створювати.
    if (enrollment.is_paid or not service.is_configured
            or not enrollment.payment_amount):
        return {'liqpay_data': None, 'liqpay_signature': None,
                'liqpay_checkout_url': None}

    order_id = enrollment.order_id
    # Гостя повертаємо на його ж сторінку замовлення: payments.success
    # вимагає логіну, тобто після оплати впер би людину в той самий бар'єр,
    # який ми щойно прибрали. ?ret=1 вмикає там опитування статусу.
    result_url = (
        url_for('online.order', token=token, ret=1, _external=True) if token
        else url_for('payments.success', order_id=order_id, _external=True)
    )
    data, signature, checkout_url = service.create_payment_form(
        order_id=order_id,
        amount=float(enrollment.payment_amount),
        description=course.effective_title,
        result_url=result_url,
        server_url=url_for('payments.liqpay_callback', _external=True),
    )
    return {'liqpay_data': data, 'liqpay_signature': signature,
            'liqpay_checkout_url': checkout_url}


# --------------------------- гостьове замовлення ---------------------------

def _load_order(token):
    return OnlineEnrollment.query.options(
        joinedload(OnlineEnrollment.course),
        joinedload(OnlineEnrollment.user),
    ).filter_by(order_token=token).first()


@online_bp.route('/order/<token>', methods=['GET', 'POST'])
@limiter.limit('60 per hour')
def order(token):
    """Сторінка замовлення для покупця без акаунта.

    Авторизація -- сам токен: людина щойно оформила покупку і входу ще не
    має. Робить усе те саме, що чекаут залогіненого: промокод, оплата,
    рахунок, а після оплати -- посилання на навчання і створення кабінету.
    """
    enrollment = _load_order(token)
    if enrollment is None or not enrollment.order_token_active:
        return render_template('online/order_invalid.html'), 410
    if enrollment.status == 'cancelled':
        return render_template('online/order_invalid.html', cancelled=True), 410

    course = enrollment.course

    # Повернення з LiqPay (?ret=1): платіж міг ще не дійти вебхуком, і без
    # опитування людина побачила б «до сплати» одразу після оплати.
    if (request.args.get('ret')
            and enrollment.payment_status in ('unpaid', 'pending')
            and enrollment.payment_amount and enrollment.payment_amount > 0):
        _poll_payment(enrollment)

    if request.method == 'POST':
        _handle_promo(enrollment, course)
        return redirect(url_for('online.order', token=token))

    if (not enrollment.is_paid and enrollment.payment_amount is not None
            and enrollment.payment_amount <= 0):
        return _complete_free_order(enrollment, course, token=token)

    return render_template(
        'online/checkout.html', **_order_context(enrollment, course, token=token))


def _poll_payment(enrollment):
    """Best-effort синхронне опитування LiqPay. Збій нічого не ламає."""
    from app.services.liqpay import get_liqpay_service
    from app.services.payment_ops import PaymentOps

    service = get_liqpay_service()
    if not service.is_configured:
        return
    try:
        PaymentOps(service).check_enrollment_and_update(enrollment)
        db.session.refresh(enrollment)
    except Exception:
        logger.exception('Failed to poll LiqPay for %s on order page',
                         enrollment.order_id)


@online_bp.route('/order/<token>/set-password', methods=['POST'])
@limiter.limit('10 per hour')
def order_set_password(token):
    """Створення кабінету одразу після покупки.

    Решта даних (ПІБ, email, телефон) уже є із замовлення, лишається пароль.
    """
    from flask_login import login_user

    enrollment = _load_order(token)
    if enrollment is None or not enrollment.order_token_active:
        return render_template('online/order_invalid.html'), 410

    user = enrollment.user
    if user is None:
        abort(404)

    back = url_for('online.order', token=token)

    # Наявний акаунт паролем НЕ перезаписуємо: інакше будь-хто, вказавши
    # чужий email на чекауті, отримав би змогу змінити пароль власника.
    if user.has_password:
        flash(_('У вас уже є кабінет — увійдіть, щоб побачити покупку.'), 'info')
        return redirect(url_for('auth.login'))

    password = request.form.get('password') or ''
    confirm = request.form.get('password_confirm') or ''
    if len(password) < 8:
        flash(_('Пароль має містити щонайменше 8 символів'), 'error')
        return redirect(back)
    if password != confirm:
        flash(_('Паролі не збігаються'), 'error')
        return redirect(back)

    user.set_password(password)
    db.session.commit()
    login_user(user)
    logger.info('Guest %s created account for user %d',
                enrollment.order_id, user.id)
    flash(_('Кабінет створено. Тут ви завжди знайдете свої курси.'), 'success')
    return redirect(url_for('auth.account'))


@online_bp.route('/order/<token>/reissue', methods=['POST'])
@limiter.limit('10 per hour')
def order_reissue(token):
    """Перевипуск посилання на навчання для покупця без акаунта.

    Без цього маршруту гість із протермінованим токеном опинявся в глухому
    куті: сторінка помилки пропонує перевипуск лише власнику акаунта, а
    акаунта в нього немає. Авторизація -- сам токен замовлення.
    """
    enrollment = _load_order(token)
    if enrollment is None or not enrollment.order_token_active:
        return render_template('online/order_invalid.html'), 410

    if not enrollment.is_paid:
        flash(_('Замовлення не оплачене'), 'error')
        return redirect(url_for('online.order', token=token))

    from app.services import sintegrum_access
    try:
        sintegrum_access.close_transaction_before_network()
        sintegrum_access.reissue(enrollment)
    except sintegrum_access.AccessProvisionError:
        flash(
            _('Не вдалося видати посилання. Ми вже розбираємось, '
              'напишіть нам, якщо це терміново.'),
            'error',
        )
        return redirect(url_for('online.order', token=token))

    return redirect(url_for('online.access', token=enrollment.access_token))


@online_bp.route('/order/<token>/invoice.pdf')
@limiter.limit('20 per hour')
def order_invoice_token(token):
    """Рахунок на оплату для покупця без акаунта."""
    enrollment = _load_order(token)
    if enrollment is None or not enrollment.order_token_active:
        return render_template('online/order_invalid.html'), 410

    return _send_invoice(enrollment, url_for('online.order', token=token))


def _send_invoice(enrollment, back_url):
    """Віддати PDF рахунка або пояснити, чому його немає.

    Спільне для обох входів -- за токеном і з кабінету: правила «після
    оплати рахунок не потрібен» і «для нуля рахунка не буває» одні.
    """
    from flask import send_file

    from app.services.invoice_service import (
        InvoiceError, invoice_filename, render_invoice_pdf,
    )

    if enrollment.is_paid:
        flash(_('Замовлення вже оплачено'), 'info')
        return redirect(back_url)

    if not enrollment.payment_amount or enrollment.payment_amount <= 0:
        flash(_('Для безкоштовного замовлення рахунок не потрібен'), 'info')
        return redirect(back_url)

    try:
        pdf = render_invoice_pdf(enrollment)
    except InvoiceError as exc:
        logger.warning('Invoice for %s failed: %s', enrollment.order_id, exc)
        flash(_('Не вдалося сформувати рахунок. Напишіть нам.'), 'error')
        return redirect(back_url)

    return send_file(
        io.BytesIO(pdf),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=invoice_filename(enrollment, 'pdf'),
    )


@online_bp.route('/access/<token>', localize=False)
@limiter.limit('30 per hour')
def access(token):
    """Тимчасове посилання на навчання.

    localize=False: посилання живе в листі, і мовний префікс тут лише
    множив би варіанти того самого токена.

    Ціль редіректу (спільне посилання реєстрації Sintegrum) не показується
    ні на сторінці помилки, ні в логах -- нею користуються лише через 302.
    """
    enrollment = OnlineEnrollment.query.filter_by(access_token=token).first()

    if enrollment is None:
        return render_template(
            'online/access_error.html', reason='unknown', enrollment=None,
        ), 404

    if not enrollment.is_paid:
        # Токен існує, але оплату скасовано або повернуто.
        return render_template(
            'online/access_error.html', reason='unpaid', enrollment=enrollment,
        ), 403

    if enrollment.access_is_expired:
        return render_template(
            'online/access_error.html', reason='expired', enrollment=enrollment,
        ), 410

    from app.services import sintegrum_access

    # Ціль -- готове посилання курсу або навчальний портал компанії: при
    # автоматичній видачі персонального посилання не існує, учасник заходить
    # під собою й бачить відкритий курс у своєму списку.
    target = sintegrum_access.target_url_for(enrollment)
    if not target:
        logger.error('Access target missing for %s', enrollment.order_id)
        return render_template(
            'online/access_error.html', reason='no_target', enrollment=enrollment,
        ), 503

    enrollment.access_last_opened_at = db.func.now()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to record access open for %s', enrollment.order_id)

    return redirect(target, code=302)


@online_bp.route('/access/<int:enrollment_id>/reissue', methods=['POST'])
@login_required
@limiter.limit('10 per hour')
def reissue_access(enrollment_id):
    """Перевипуск протермінованого посилання на вимогу учасника."""
    enrollment = db.session.get(OnlineEnrollment, enrollment_id)
    if enrollment is None or enrollment.user_id != current_user.id:
        abort(404)

    if not enrollment.is_paid:
        flash(_('Замовлення не оплачене'), 'error')
        return redirect(url_for('auth.account'))

    from app.services import sintegrum_access
    try:
        sintegrum_access.close_transaction_before_network()
        sintegrum_access.reissue(enrollment)
    except sintegrum_access.AccessProvisionError:
        flash(
            _('Не вдалося видати посилання. Ми вже розбираємось, '
              'напишіть нам, якщо це терміново.'),
            'error',
        )
        return redirect(url_for('auth.account'))

    flash(_('Нове посилання на навчання видано'), 'success')
    return redirect(url_for('online.access', token=enrollment.access_token))


@online_bp.route('/orders/<int:enrollment_id>/invoice.pdf')
@login_required
@limiter.limit('20 per hour')
def order_invoice(enrollment_id):
    """Рахунок на оплату онлайн-курсу.

    Потрібен юрособам: клініка платить за навчання співробітника з рахунку,
    а не карткою. Для заходів такий рахунок є давно -- тут була дірка, через
    яку такі покупці просто не могли купити.

    Доступний, поки замовлення не оплачене: після оплати рахунок ролі не
    грає, а от «сплатіть ще раз» у пошті плутає.
    """
    enrollment = db.session.get(OnlineEnrollment, enrollment_id)
    if enrollment is None or enrollment.user_id != current_user.id:
        abort(404)

    return _send_invoice(
        enrollment, url_for('online.checkout', slug=enrollment.course.slug))
