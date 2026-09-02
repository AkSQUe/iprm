import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from flask import (
    render_template, redirect, url_for, flash, request, send_file, jsonify,
)
from flask_login import current_user
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from app.admin import _listing, admin_bp
from app.admin._helpers import try_commit
from app.admin.decorators import admin_required
from app.auth._helpers import is_safe_redirect_url
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.trainer import Trainer
from app.models.user import User

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


def _redirect_after_action(reg):
    """Куди повернутись після дії в рядку списку.

    Форми списку шлють у next поточний URL сторінки разом із фільтрами і
    номером сторінки -- інакше менеджер після кожної дії опинявся б на
    початку невідфільтрованого списку. Значення приходить з форми, тож
    пропускаємо лише внутрішні відносні шляхи.
    """
    target = request.form.get('next', '')
    if is_safe_redirect_url(target):
        return redirect(target)
    # Форми зі старим маркером (сторінка з кешу браузера).
    if target == 'registrations_all':
        return redirect(url_for('admin.registrations_all'))
    if reg.instance_id:
        return redirect(url_for('admin.instance_registrations', instance_id=reg.instance_id))
    return redirect(url_for('admin.registrations_all'))


@admin_bp.route('/instances/<int:instance_id>/registrations')
@admin_required
def instance_registrations(instance_id):
    instance = db.session.query(CourseInstance).options(
        joinedload(CourseInstance.course),
    ).filter_by(id=instance_id).first()
    if not instance:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    filters = {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', dict(EventRegistration.STATUSES)),
        'payment': _listing.choice_arg(
            'payment', dict(EventRegistration.PAYMENT_STATUSES)),
    }

    # medical_profile вантажимо одразу -- для колонки "Анкета" (менеджер бачить,
    # кому нагадати перед видачею сертифікатів) без N+1.
    query = EventRegistration.query.options(
        joinedload(EventRegistration.user).joinedload(User.medical_profile),
        joinedload(EventRegistration.certificate),
        # Колонка "Тестування" показує найкращий результат -- без цього рядок
        # тягнув би спроби окремим запитом.
        joinedload(EventRegistration.quiz_attempts),
        # Колонка "Сума" показує код знижки -- без цього рядок на кожну
        # реєстрацію тягнув би окремий SELECT.
        joinedload(EventRegistration.promo_code),
        # Та сама колонка показує назву тарифу (instance_registrations.html).
        joinedload(EventRegistration.tariff),
    ).filter(EventRegistration.instance_id == instance.id)

    if filters['q']:
        query = query.join(User, EventRegistration.user_id == User.id)
        query = _listing.apply_search(query, filters['q'], [
            User.email, User.first_name, User.last_name, EventRegistration.phone,
        ])
    if filters['status']:
        query = query.filter(EventRegistration.status == filters['status'])
    if filters['payment']:
        query = query.filter(EventRegistration.payment_status == filters['payment'])

    # Пагінація тут не про сьогоднішній обсяг (у проді ~10 реєстрацій на
    # проведення), а про те, що сторінка будує на кожен рядок стан тестування,
    # анкети й сертифіката. `.all()` означав, що вебінар на 300 осіб рахував би
    # це все за один запит -- і батч-контекст будувався б на 300 рядків замість
    # 50. Лічильники нижче навмисно лишаються по всьому заходу.
    page = _listing.page_arg()
    per_page = _listing.per_page_arg()
    pagination = query.order_by(EventRegistration.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False,
    )
    registrations = pagination.items

    # Лічильники -- по ВСЬОМУ заходу: скільки людей записано, не залежить від
    # того, що зараз шукає менеджер.
    stat_rows = db.session.query(
        EventRegistration.status, func.count(EventRegistration.id),
    ).filter(
        EventRegistration.instance_id == instance.id,
    ).group_by(EventRegistration.status).all()
    counts = dict(stat_rows)
    # Місця тримають лише оплачені (services.seating), тому "зайнято" не
    # дорівнює ані total, ані confirmed. Перевищення пулу шаблон показує
    # червоним -- воно легальне (гроші прийняті), але потребує реакції.
    from app.services.seating import occupied_count
    occupied = occupied_count(instance.id)
    capacity = instance.effective_max_participants
    stats = {
        'total': sum(counts.values()),
        'confirmed': counts.get('confirmed', 0),
        'pending': counts.get('pending', 0),
        'completed': counts.get('completed', 0),
        'occupied': occupied,
        'capacity': capacity,
        'overbooked': capacity is not None and occupied > capacity,
    }

    # Стан тестування на кожен рядок. Саме `eligibility_map`, а не виклик на
    # кожну реєстрацію: поштучно це давало +5 SELECT на рядок, а тут рядків
    # стільки ж, скільки учасників у групі.
    from app.services import quiz_service
    # Контекст один на сторінку: `resolve_quiz` без нього перечитував ті самі
    # два рядки `course_quizzes`. На порожньому списку контекст не передаємо --
    # у ньому не було б ні перевизначення, ні тесту курсу (див. коментар у
    # routes_quizzes.instance_quiz_results).
    quiz_context = (quiz_service.build_batch_context(registrations)
                    if registrations else None)
    quiz_states = quiz_service.eligibility_map(registrations, context=quiz_context)

    # Незакрита доплата -- одним запитом на сторінку, а не перевіркою на
    # рядок: поштучно це був би рівно той N+1, від якого стереже
    # test_page_does_not_grow_with_participants. Умова спільна з
    # запобіжником 11 і з фільтром списку (transfer_service).
    from app.services import transfer_service
    surcharge_due = transfer_service.unpaid_surcharge_amounts(
        [r.id for r in registrations])

    return render_template(
        'admin/instance_registrations.html',
        instance=instance,
        registrations=registrations,
        pagination=pagination,
        stats=stats,
        filters=filters,
        status_options=EventRegistration.STATUSES,
        payment_options=EventRegistration.PAYMENT_STATUSES,
        quiz_states=quiz_states,
        quiz_statuses=quiz_service,
        quiz=quiz_service.resolve_quiz(instance, quiz_context),
        surcharge_due=surcharge_due,
        # Один набір параметрів на пілюлі, пагінацію й експорт -- усі три мусять
        # вести на той самий зріз (як у registrations_all).
        filter_args=_listing.filter_args(filters),
    )


def _wants_json():
    """Inline-редагування в таблиці шле fetch з X-Requested-With."""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


@admin_bp.route('/registrations/<int:reg_id>/status', methods=['POST'])
@admin_required
def registration_status(reg_id):
    xhr = _wants_json()
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        if xhr:
            return jsonify({'ok': False, 'error': 'Реєстрацію не знайдено'}), 404
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    new_status = request.form.get('status')
    if new_status not in dict(EventRegistration.STATUSES):
        if xhr:
            return jsonify({'ok': False, 'error': 'Невідомий статус'}), 400
        return _redirect_after_action(reg)

    old_status = reg.status
    reg.status = new_status
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s changed reg %d status: %s -> %s',
            current_user.email, reg_id, old_status, new_status,
        )
        try:
            from app.services.email_service import EmailService
            EmailService.send_status_change(reg, old_status, new_status)
        except Exception:
            logger.exception('Failed to queue status change email for reg %d', reg_id)
        if xhr:
            return jsonify({'ok': True, 'value': reg.status, 'label': reg.status_label})
        flash(f'Статус змінено на "{reg.status_label}"', 'success')
    except Exception:
        logger.exception('Failed to update registration %d status', reg_id)
        db.session.rollback()
        if xhr:
            return jsonify({'ok': False, 'error': 'Помилка при оновленні'}), 500
        flash('Помилка при оновленні', 'error')

    return _redirect_after_action(reg)


@admin_bp.route('/registrations/<int:reg_id>/payment', methods=['POST'])
@admin_required
def registration_payment(reg_id):
    """Змінити статус оплати (inline-select у таблиці). При переході в 'paid'
    призначаємо номер місця (узгоджено з participant_service)."""
    xhr = _wants_json()
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        if xhr:
            return jsonify({'ok': False, 'error': 'Реєстрацію не знайдено'}), 404
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.registrations_all'))

    new_ps = request.form.get('payment')
    if new_ps not in dict(EventRegistration.PAYMENT_STATUSES):
        if xhr:
            return jsonify({'ok': False, 'error': 'Невідомий статус оплати'}), 400
        return _redirect_after_action(reg)

    old_ps = reg.payment_status
    reg.payment_status = new_ps
    if new_ps == 'paid' and reg.status != 'cancelled' and reg.place_number is None:
        try:
            from app.services import registration_service
            registration_service.assign_place_number(reg)
        except Exception:
            logger.exception('Failed to assign place_number for reg %d', reg_id)
    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s changed reg %d payment: %s -> %s',
            current_user.email, reg_id, old_ps, new_ps,
        )
        # Реферальні бали: нарахувати/анулювати відповідно до нового статусу.
        try:
            from app.services import referral_service
            referral_service.sync_reward_for_registration(reg)
        except Exception:
            logger.exception('Referral reward sync failed for reg %d', reg_id)
        # Ручна відмітка оплати так само може перевищити пул -- сигналимо
        # тим самим шляхом, що й LiqPay-callback (services.seating).
        if new_ps == 'paid':
            from app.services.seating import notify_overbooking_if_needed
            notify_overbooking_if_needed(reg)
        if xhr:
            return jsonify({
                'ok': True, 'value': reg.payment_status,
                'label': reg.payment_status_label, 'place_number': reg.place_number,
            })
        flash(f'Оплату змінено на "{reg.payment_status_label}"', 'success')
    except Exception:
        logger.exception('Failed to update registration %d payment', reg_id)
        db.session.rollback()
        if xhr:
            return jsonify({'ok': False, 'error': 'Помилка при оновленні'}), 500
        flash('Помилка при оновленні', 'error')

    return _redirect_after_action(reg)


@admin_bp.route('/registrations/<int:reg_id>/attendance', methods=['POST'])
@admin_required
def registration_attendance(reg_id):
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    reg.attended = True
    reg.status = 'completed'
    cpd = request.form.get('cpd_points', type=int)
    # max cap = 2x the instance's effective cpd (або принаймні 100)
    base_cpd = reg.instance.effective_cpd_points if reg.instance else 0
    max_cpd = (base_cpd or 0) * 2
    if cpd is not None and (cpd < 0 or cpd > max(max_cpd, 100)):
        flash('Некоректна кількість балів БПР', 'error')
        return _redirect_after_action(reg)
    reg.cpd_points_awarded = cpd if cpd is not None else base_cpd

    try:
        db.session.commit()
        audit_logger.info(
            'Admin %s confirmed attendance reg %d, CPD=%s',
            current_user.email, reg_id, reg.cpd_points_awarded,
        )
        flash(f'Присутність підтверджено, нараховано {reg.cpd_points_awarded} балів БПР', 'success')
    except Exception:
        logger.exception('Failed to update attendance for registration %d', reg_id)
        db.session.rollback()
        flash('Помилка при оновленні', 'error')

    return _redirect_after_action(reg)


@admin_bp.route('/registrations/<int:reg_id>/certificate', methods=['POST'])
@admin_required
def registration_certificate_issue(reg_id):
    """Видати сертифікат: створити запис, згенерувати PDF, надіслати email."""
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    if reg.status == 'cancelled':
        flash('Не можна видати сертифікат для скасованої реєстрації', 'error')
        return _redirect_after_action(reg)

    try:
        from app.services.certificate_service import issue_certificate
        cert = issue_certificate(reg, issued_by=current_user)
        # Капчимо локально до email-call: якщо send_certificate упаде і
        # залишить сесію в rolled-back-стані, лінива перезагрузка cert.number
        # у flash нижче кине PendingRollbackError.
        cert_number = cert.number
        audit_logger.info(
            'Admin %s issued certificate %s for reg %d',
            current_user.email, cert_number, reg_id,
        )
        try:
            from app.services.email_service import EmailService
            EmailService.send_certificate(cert)
            email_sent = True
        except Exception:
            # Сертифікат уже у БД (issue_certificate commit-нув). Email -- best-
            # effort, тож відкочуємо тільки failed-INSERT email_logs.
            db.session.rollback()
            logger.exception('Failed to email certificate for reg %d', reg_id)
            email_sent = False
        if email_sent:
            flash(f'Сертифікат {cert_number} видано та надіслано на email', 'success')
        else:
            flash(
                f'Сертифікат {cert_number} видано. Email не відправлено – '
                'надішліть повторно з картки реєстрації.',
                'warning',
            )
    except ValueError as exc:
        # Відсутні дані для номера БПР (провайдер/захід) -- показуємо причину.
        db.session.rollback()
        flash(str(exc), 'error')
    except Exception:
        logger.exception('Failed to issue certificate for reg %d', reg_id)
        db.session.rollback()
        flash('Помилка при видачі сертифіката', 'error')

    return _redirect_after_action(reg)


@admin_bp.route('/registrations/<int:reg_id>/certificate/resend', methods=['POST'])
@admin_required
def registration_certificate_resend(reg_id):
    """Повторно надіслати вже виданий сертифікат на email."""
    reg = db.session.get(EventRegistration, reg_id)
    if not reg or reg.certificate is None:
        flash('Сертифікат не знайдено', 'error')
        return redirect(url_for('admin.registrations_all'))

    try:
        from app.services.email_service import EmailService
        EmailService.send_certificate(reg.certificate)
        audit_logger.info(
            'Admin %s resent certificate %s for reg %d',
            current_user.email, reg.certificate.number, reg_id,
        )
        flash('Сертифікат повторно надіслано на email', 'success')
    except Exception:
        logger.exception('Failed to resend certificate for reg %d', reg_id)
        flash('Помилка при надсиланні сертифіката', 'error')

    return _redirect_after_action(reg)


@admin_bp.route('/registrations/<int:reg_id>/certificate/download')
@admin_required
def registration_certificate_download(reg_id):
    """Завантажити PDF сертифіката (адмін)."""
    reg = db.session.get(EventRegistration, reg_id)
    if not reg or reg.certificate is None:
        flash('Сертифікат не знайдено', 'error')
        return redirect(url_for('admin.registrations_all'))

    from app.services.certificate_service import certificate_abs_path, regenerate_pdf
    cert = reg.certificate
    path = certificate_abs_path(cert)
    if not os.path.exists(path):
        regenerate_pdf(cert)
    return send_file(
        path,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'{cert.number}.pdf',
    )


@admin_bp.route('/certificates/<int:cert_id>/revoke', methods=['POST'])
@admin_required
def certificate_revoke(cert_id):
    """Відкликати або відновити сертифікат (toggle)."""
    from app.models.certificate import Certificate
    from app.models.mixins import utcnow

    cert = db.session.get(Certificate, cert_id)
    if not cert:
        flash('Сертифікат не знайдено', 'error')
        return redirect(url_for('admin.certificates'))

    cert.revoked = not cert.revoked
    cert.revoked_at = utcnow() if cert.revoked else None
    try:
        db.session.commit()
        action = 'відкликано' if cert.revoked else 'відновлено'
        audit_logger.info(
            'Admin %s %s certificate %s', current_user.email, action, cert.number,
        )
        flash(f'Сертифікат {cert.number} {action}', 'success')
    except Exception:
        logger.exception('Failed to toggle revoke for certificate %d', cert_id)
        db.session.rollback()
        flash('Помилка при оновленні', 'error')

    return redirect(url_for('admin.certificates'))


# Пресети -- поширені щоденні зрізи в один клік. Кожен лише виставляє ті
# самі параметри фільтра, тож пресет, панель, експорт і пагінація говорять
# однією мовою; жодної окремої гілки в запиті.
REGISTRATION_PRESETS = {
    'unpaid': {
        'label': 'Неоплачені',
        'icon': 'error',
        'args': {'payment': 'unpaid', 'status': 'confirmed'},
    },
    'no_certificate': {
        'label': 'Без сертифіката',
        'icon': 'workspace_premium',
        'args': {'status': 'completed'},
    },
    'today': {
        'label': 'Сьогоднішні',
        'icon': 'event',
        'args': {},  # діапазон дат підставляємо на льоту -- «сьогодні» рухоме
    },
}


def _preset_args(key):
    """Параметри пресету у вигляді, придатному для url_for."""
    preset = REGISTRATION_PRESETS.get(key)
    if preset is None:
        return {}
    args = dict(preset['args'])
    if key == 'today':
        today = _listing.now_kyiv().strftime('%Y-%m-%d')
        args.update({'date_from': today, 'date_to': today})
    if key == 'no_certificate':
        args['no_certificate'] = '1'
    return args


def _preset_matches(key, filters):
    """Чи поточний зріз -- це рівно цей пресет (щоб підсвітити пілюлю)."""
    return all(
        str(filters.get(name) or '') == str(value)
        for name, value in _preset_args(key).items()
    )


def _registration_filters():
    """Фільтри списку реєстрацій з query-string.

    Спільні для сторінки і для xlsx-експорту: файл має містити рівно той
    зріз, який менеджер бачить на екрані.
    """
    # Швидкий фільтр за часом заходу. За замовчуванням -- лише майбутні заходи,
    # щоб не показувати тисячі нерелевантних реєстрацій на минулі події.
    scope = _listing.choice_arg('scope', ('upcoming', 'past', 'all'), 'upcoming')
    return {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', dict(EventRegistration.STATUSES)),
        'payment': _listing.choice_arg('payment', dict(EventRegistration.PAYMENT_STATUSES)),
        'payment_method': _listing.choice_arg(
            'payment_method', dict(EventRegistration.PAYMENT_METHODS)),
        'instance_id': _listing.int_arg('instance_id'),
        'course_id': _listing.int_arg('course_id'),
        'trainer_id': _listing.int_arg('trainer_id'),
        # Тільки для переходу з картки користувача -- у філтр-барі поля нема.
        'user_id': _listing.int_arg('user_id'),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'no_certificate': _listing.choice_arg('no_certificate', ('1',)),
        'surcharge': _listing.choice_arg('surcharge', ('due',)),
        'scope': scope,
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _apply_registration_filters(query, filters):
    """Накласти фільтри `_registration_filters` на запит EventRegistration."""
    course_id_filter = filters['course_id']
    trainer_id_filter = filters['trainer_id']
    scope = filters['scope']

    if filters['q']:
        # Пошук по учаснику: ПІБ/email живуть у User, телефон -- у самій
        # реєстрації (він міг відрізнятись від профілю).
        query = query.join(User, EventRegistration.user_id == User.id)
        query = _listing.apply_search(query, filters['q'], [
            User.email, User.first_name, User.last_name, EventRegistration.phone,
        ])
    if filters['status']:
        query = query.filter(EventRegistration.status == filters['status'])
    if filters['payment']:
        query = query.filter(EventRegistration.payment_status == filters['payment'])
    if filters['payment_method']:
        query = query.filter(
            EventRegistration.payment_method == filters['payment_method'])
    if filters['instance_id']:
        query = query.filter(EventRegistration.instance_id == filters['instance_id'])
    if filters['user_id']:
        query = query.filter(EventRegistration.user_id == filters['user_id'])
    query = _listing.apply_date_range(
        query, EventRegistration.created_at,
        filters['date_from'], filters['date_to'],
    )
    if filters['no_certificate']:
        # Кому ще не видали документ: підстава для пресету «Без сертифіката».
        query = query.filter(~EventRegistration.certificate.has())
    if filters.get('surcharge') == 'due':
        from app.models.registration_transfer import RegistrationTransfer
        from app.services import transfer_service
        query = query.filter(EventRegistration.id.in_(
            db.session.query(RegistrationTransfer.registration_id).filter(
                *transfer_service.unpaid_surcharge_condition()
            )
        ))

    # CourseInstance потрібен для scope (час заходу) та фільтрів курс/тренер.
    # Джойнимо один раз, щоб не дублювати join.
    if scope != 'all' or course_id_filter or trainer_id_filter:
        query = query.join(
            CourseInstance, EventRegistration.instance_id == CourseInstance.id,
        )
        if course_id_filter:
            query = query.filter(CourseInstance.course_id == course_id_filter)
        if trainer_id_filter:
            # Ефективний тренер: trainer заходу, інакше -- тренер курсу (fallback).
            query = query.join(
                Course, CourseInstance.course_id == Course.id,
            ).filter(
                func.coalesce(CourseInstance.trainer_id, Course.trainer_id)
                == trainer_id_filter
            )
        if scope != 'all':
            now = datetime.now(timezone.utc)
            if scope == 'upcoming':
                # Майбутні + заходи без дати (TBD) -- не вважаємо їх минулими.
                query = query.filter(
                    (CourseInstance.start_date >= now)
                    | (CourseInstance.start_date.is_(None))
                )
            else:  # past
                query = query.filter(CourseInstance.start_date < now)
    return query


@admin_bp.route('/registrations')
@admin_required
def registrations_all():
    filters = _registration_filters()
    page = _listing.page_arg()
    per_page = _listing.per_page_arg()

    stats = db.session.query(
        func.count().label('total'),
        func.count(case((EventRegistration.status == 'confirmed', 1))).label('confirmed'),
        func.count(case((EventRegistration.status == 'pending', 1))).label('pending'),
        func.count(case((EventRegistration.status == 'cancelled', 1))).label('cancelled'),
        func.coalesce(
            func.sum(case((EventRegistration.payment_status == 'paid', EventRegistration.payment_amount))),
            0,
        ).label('total_paid'),
    ).one()

    query = _apply_registration_filters(
        EventRegistration.query.options(
            # medical_profile і quiz_attempts -- для колонок прогресу
            # (_registration_progress.html). Учасники тут різні, тож без
            # eager-load кожен рядок тягнув би анкету й спроби окремо.
            joinedload(EventRegistration.user).joinedload(User.medical_profile),
            joinedload(EventRegistration.quiz_attempts),
            joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
            joinedload(EventRegistration.certificate),
            joinedload(EventRegistration.promo_code),
        ),
        filters,
    )

    pagination = query.order_by(EventRegistration.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False,
    )

    # Реферальна атрибуція: резолв кодів у імена рефереров (bulk, без N+1).
    from app.services import referral_service
    referrer_map = referral_service.resolve_referrers_bulk(
        [r.referral_code for r in pagination.items],
    )

    # Стан тестування -- лише для рядків цієї сторінки, одним набором запитів.
    from app.services import quiz_service
    quiz_states = quiz_service.eligibility_map(pagination.items)

    return render_template(
        'admin/registrations.html',
        registrations=pagination.items,
        pagination=pagination,
        stats=stats,
        referrer_map=referrer_map,
        quiz_states=quiz_states,
        quiz_statuses=quiz_service,
        filters=filters,
        # Непорожні параметри -- один набір для пілюль, пагінації й експорту:
        # усі три мають вести на той самий зріз.
        filter_args=_listing.filter_args(filters),
        presets=[
            (key, preset['label'], preset['icon'], _preset_args(key))
            for key, preset in REGISTRATION_PRESETS.items()
        ],
        active_preset=next(
            (key for key in REGISTRATION_PRESETS
             if _preset_matches(key, filters)), None,
        ),
        status_options=EventRegistration.STATUSES,
        payment_options=EventRegistration.PAYMENT_STATUSES,
        method_options=EventRegistration.PAYMENT_METHODS,
        per_page_options=_listing.PER_PAGE_OPTIONS,
        **_registration_select_options(),
    )


def _registration_select_options():
    """Довідники для селектів фільтра: курси / тренери / заходи.

    Тягнемо лише колонки, які потрібні селекту (id + підпис), а не цілі
    сутності з joinedload: список заходів росте з кожним проведенням, і
    гідратувати сотні ORM-обʼєктів заради двох рядків тексту -- марно.
    """
    from app.services import participant_service

    instance_rows = db.session.query(
        CourseInstance.id, CourseInstance.start_date,
        CourseInstance.location, Course.title,
    ).join(Course, CourseInstance.course_id == Course.id).order_by(
        CourseInstance.start_date.desc(),
    ).all()
    return {
        'course_options': db.session.query(
            Course.id, Course.title,
        ).order_by(Course.title).all(),
        'trainer_options': db.session.query(
            Trainer.id, Trainer.full_name,
        ).order_by(Trainer.full_name).all(),
        'instance_options': [
            (
                inst_id,
                participant_service.format_event_label(title, start_date)
                + (f' ({location})' if location else ''),
            )
            for inst_id, start_date, location, title in instance_rows
        ],
    }


_SCOPE_LABELS = {
    'upcoming': 'Майбутні заходи (та заходи без дати)',
    'past': 'Минулі заходи',
    'all': 'Усі заходи',
}


def _registration_filters_summary(filters, rows_count):
    """Людиночитний опис активних фільтрів для аркуша «Фільтри» у файлі."""
    summary = [
        ('Період заходів', _SCOPE_LABELS.get(filters['scope'], filters['scope'])),
        ('Пошук', filters['q'] or '–'),
        ('Дата реєстрації', _listing.date_range_label(filters)),
    ]

    status = dict(EventRegistration.STATUSES).get(filters['status'])
    summary.append(('Статус', status or 'Усі'))
    payment = dict(EventRegistration.PAYMENT_STATUSES).get(filters['payment'])
    summary.append(('Оплата', payment or 'Усі'))
    method = dict(EventRegistration.PAYMENT_METHODS).get(filters['payment_method'])
    summary.append(('Спосіб оплати', method or 'Усі'))

    course = db.session.get(Course, filters['course_id']) if filters['course_id'] else None
    summary.append(('Курс', course.title if course else 'Усі'))
    trainer = db.session.get(Trainer, filters['trainer_id']) if filters['trainer_id'] else None
    summary.append(('Тренер', trainer.full_name if trainer else 'Усі'))

    instance = (
        db.session.get(CourseInstance, filters['instance_id'])
        if filters['instance_id'] else None
    )
    if instance:
        from app.services import participant_service
        summary.append(('Захід', participant_service.event_label(instance)))
    else:
        summary.append(('Захід', 'Усі'))

    # no_certificate -- прапорець, а не список значень: рядок пишемо лише
    # коли фільтр активний, інакше файл на звичайний зріз друкував би «Ні»,
    # хоча фільтра там просто немає. Підпис і значення -- дослівно ті самі,
    # що в чіпсі й опції `<select>` у registrations.html (`'Сертифікат'` /
    # `'Ще не виданий'`): файл називає те, що людина щойно бачила на екрані.
    if filters['no_certificate']:
        summary.append(('Сертифікат', 'Ще не виданий'))

    if filters['surcharge']:
        summary.append(('Доплата', 'Не надійшла'))

    # user_id -- перехід із картки користувача (немає поля у філтр-барі, тож
    # серед фільтрів вище цього рядка нема): без нього файл на одну людину
    # звітував би "Курс: Усі, Захід: Усі, Статус: Усі" -- правда про кожен
    # окремий фільтр і неправда про сам зріз.
    user = db.session.get(User, filters['user_id']) if filters['user_id'] else None
    if user:
        summary.append(('Учасник', user.full_name or user.email))
    elif filters['user_id']:
        # Рахунок ще існує, а ПІБ/email прочитати нема з чого (видалений
        # користувач) -- краще id, ніж мовчки пропустити рядок.
        summary.append(('Учасник', f'ID {filters["user_id"]}'))
    else:
        summary.append(('Учасник', 'Усі'))

    return _listing.export_summary(summary, rows_count)


@admin_bp.route('/registrations/export')
@admin_required
def registrations_export():
    """Експорт списку реєстрацій у xlsx з урахуванням активних фільтрів.

    Вивантажує ВЕСЬ відфільтрований зріз, а не поточну сторінку: пагінація --
    властивість екрана, а не звіту.
    """
    from app.services import referral_service, xlsx_reports

    filters = _registration_filters()
    query = _apply_registration_filters(
        EventRegistration.query.options(
            joinedload(EventRegistration.user),
            # Колонка «Тренер» -- ефективний тренер (заходу або курсу), тож
            # тягнемо обидві звʼязки одразу, інакше N+1 на кожен рядок.
            joinedload(EventRegistration.instance).joinedload(CourseInstance.trainer),
            joinedload(EventRegistration.instance)
            .joinedload(CourseInstance.course).joinedload(Course.trainer),
            joinedload(EventRegistration.certificate),
            joinedload(EventRegistration.promo_code),
        ),
        filters,
    )
    query = query.order_by(EventRegistration.created_at.desc())
    # Стелю рядків міряємо COUNT-ом ДО вибірки (export_query знімає
    # сортування лише для COUNT-у, `.order_by(None)`, і рахує по ЦЬОМУ
    # запиту) -- інакше зріз на сотню тисяч реєстрацій спершу піднімався б
    # у пам'ять цілком, з усіма приєднаними об'єктами.
    regs, refusal = _listing.export_query(
        query, 'admin.registrations_all', **_listing.filter_args(filters),
    )
    if refusal:
        return refusal

    referrer_map = referral_service.resolve_referrers_bulk(
        [r.referral_code for r in regs],
    )

    def build():
        return xlsx_reports.export_registrations_xlsx(
            regs, referrer_map,
            applied_filters=_registration_filters_summary(filters, len(regs)),
        )

    audit_logger.info(
        'Admin %s exported registrations xlsx (%d rows, filters=%s)',
        current_user.email, len(regs), filters,
    )
    return _listing.xlsx_export(
        regs, 'registrations', build,
        'admin.registrations_all', **_listing.filter_args(filters),
    )


@admin_bp.route('/registrations/<int:reg_id>/completion-link', methods=['POST'])
@admin_required
def registration_completion_link(reg_id):
    """Видати (або перевикористати) токен і повернути посилання на самостійне
    завершення реєстрації учасником. JSON для copy-to-clipboard у JS."""
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        return jsonify({'ok': False, 'error': 'Реєстрацію не знайдено'}), 404
    if not reg.completion_token_active:
        reg.issue_completion_token()
        if not try_commit(log_context=f'completion_link reg={reg_id}'):
            return jsonify({'ok': False, 'error': 'Помилка збереження'}), 500
        audit_logger.info(
            'Admin %s issued completion link for reg %s', current_user.email, reg_id,
        )
    url = url_for(
        'registration.complete_registration',
        token=reg.completion_token, _external=True,
    )
    return jsonify({'ok': True, 'url': url})


@admin_bp.route('/registrations/<int:reg_id>/completion-link/email', methods=['POST'])
@admin_required
def registration_completion_link_email(reg_id):
    """Видати токен (за потреби) і НАДІСЛАТИ учаснику посилання на самостійне
    завершення реєстрації листом. Лише для учасників із реальним email."""
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        return jsonify({'ok': False, 'error': 'Реєстрацію не знайдено'}), 404
    if reg.status == 'cancelled':
        return jsonify({'ok': False, 'error': 'Реєстрацію скасовано'}), 400
    if not reg.user_has_real_email:
        return jsonify({'ok': False, 'error': 'У учасника немає реального email'}), 400

    if not reg.completion_token_active:
        reg.issue_completion_token()
        if not try_commit(log_context=f'completion_link_email reg={reg_id}'):
            return jsonify({'ok': False, 'error': 'Помилка збереження'}), 500

    url = url_for(
        'registration.complete_registration',
        token=reg.completion_token, _external=True,
    )
    try:
        from app.services.email_service import EmailService
        result = EmailService.send_completion_link(reg, url)
    except Exception:
        logger.exception('Failed to send completion link email for reg %s', reg_id)
        return jsonify({'ok': False, 'error': 'Помилка надсилання листа'}), 500

    if result is None:
        return jsonify({'ok': True, 'message': 'Лист уже надсилали нещодавно'})
    if getattr(result, 'status', None) == 'failed':
        return jsonify({'ok': False, 'error': result.error_message or 'Лист не надіслано'}), 502
    audit_logger.info(
        'Admin %s emailed completion link for reg %s to %s',
        current_user.email, reg_id, reg.user.email,
    )
    return jsonify({'ok': True, 'message': f'Лист надіслано на {reg.user.email}'})


@admin_bp.route('/registrations/<int:reg_id>/invoice.<ext>')
@admin_required
def registration_invoice_download(reg_id, ext):
    """Завантажити рахунок: ext=xlsx (Excel-оригінал) або pdf (конвертація)."""
    reg = db.session.get(EventRegistration, reg_id)
    if not reg:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.registrations_all'))

    from app.services.invoice_service import (
        InvoiceError, build_invoice_xlsx, invoice_filename, render_invoice_pdf,
    )
    back = (
        url_for('admin.instance_registrations', instance_id=reg.instance_id)
        if reg.instance_id else url_for('admin.registrations_all')
    )
    if ext == 'xlsx':
        data = build_invoice_xlsx(reg)
        audit_logger.info('Admin %s downloaded xlsx invoice reg %s', current_user.email, reg_id)
        return send_file(
            data,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=invoice_filename(reg, 'xlsx'),
            max_age=0,
        )
    if ext == 'pdf':
        try:
            pdf = render_invoice_pdf(reg)
        except InvoiceError as exc:
            flash(str(exc), 'error')
            return redirect(back)
        audit_logger.info('Admin %s downloaded pdf invoice reg %s', current_user.email, reg_id)
        # send_file коректно кодує кирилицю у назві (RFC 5987 filename*).
        import io
        return send_file(
            io.BytesIO(pdf),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=invoice_filename(reg, 'pdf'),
            max_age=0,
        )
    flash('Невідомий формат рахунка', 'error')
    return redirect(back)


@admin_bp.route('/registrations/<int:reg_id>/transfer/options')
@admin_required
def registration_transfer_options(reg_id):
    """Дані для модалки перенесення: придатні заходи, тарифи, різниці.

    Арифметика грошей рахується ТУТ, а не в JS: інакше сума в модалці й
    сума в листі одного дня розійдуться, і дізнаємось ми про це від
    учасника.
    """
    from app.services import transfer_service

    reg = EventRegistration.query.get_or_404(reg_id)
    problems = transfer_service.check(reg)
    paid = Decimal(str(reg.payment_amount or 0))

    instances = []
    for item in transfer_service.eligible_instances(reg):
        tariffs = [
            {
                'id': t.id,
                'name': t.name,
                'price': float(t.price or 0),
                'difference': float(Decimal(str(t.price or 0)) - paid),
            }
            for t in item.tariffs if t.is_active
        ]
        instances.append({
            'id': item.id,
            'title': item.course.title if item.course else 'Захід',
            'start_date': (item.start_date.strftime('%d.%m.%Y')
                           if item.start_date else ''),
            'location': item.location or '',
            'price': float(item.price or 0),
            'difference': float(Decimal(str(item.price or 0)) - paid),
            'tariffs': tariffs,
        })

    return jsonify({
        'paid': float(paid),
        'problems': problems,
        'instances': instances,
    })


@admin_bp.route('/registrations/<int:reg_id>/transfer', methods=['POST'])
@admin_required
def registration_transfer(reg_id):
    """Перенести реєстрацію на інше проведення."""
    from app.models.instance_tariff import InstanceTariff
    from app.services import transfer_service

    reg = EventRegistration.query.get_or_404(reg_id)
    target = CourseInstance.query.get(
        request.form.get('instance_id', type=int) or 0)
    if target is None:
        flash('Оберіть захід, на який переносимо', 'error')
        return _redirect_after_action(reg)

    tariff = None
    tariff_id = request.form.get('tariff_id', type=int)
    if tariff_id:
        tariff = InstanceTariff.query.filter_by(
            id=tariff_id, instance_id=target.id).first()
        if tariff is None:
            flash('Обраний тариф не належить цьому заходу', 'error')
            return _redirect_after_action(reg)

    try:
        transfer = transfer_service.execute(
            reg,
            target_instance=target,
            initiator=request.form.get('initiator', 'participant'),
            tariff=tariff,
            tariff_decision=request.form.get('tariff_decision', 'keep'),
            reason=request.form.get('reason'),
            note=request.form.get('note'),
            announced=bool(request.form.get('announced')),
            admin_user=current_user,
        )
    except ValueError as exc:
        for problem in exc.args[0]:
            flash(problem, 'error')
        return _redirect_after_action(reg)

    if transfer.announced:
        flash('Учасника перенесено, лист із вибором надіслано', 'success')
    else:
        flash('Учасника перенесено', 'success')

    # Переїзд відбувся, а заявку на різницю завести не вдалося (реєстрація
    # не оплачена, гроші вже повернуті). Мовчати не можна: адмін інакше
    # певен, що заявка в черзі, і чекає її там.
    if transfer.refund_claim_problem:
        flash(f'Заявку на повернення різниці НЕ заведено: '
              f'{transfer.refund_claim_problem}', 'warning')
    return _redirect_after_action(reg)
