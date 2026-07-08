import logging
import os
from datetime import datetime, timezone
from flask import (
    render_template, redirect, url_for, flash, request, send_file, jsonify,
)
from flask_login import current_user
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin._helpers import try_commit
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.trainer import Trainer

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


def _redirect_after_action(reg):
    if request.form.get('next') == 'registrations_all':
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

    # medical_profile вантажимо одразу -- для позначки "анкета не заповнена"
    # (менеджер бачить, кому нагадати перед видачею сертифікатів) без N+1.
    from app.models.user import User
    registrations = EventRegistration.query.options(
        joinedload(EventRegistration.user).joinedload(User.medical_profile),
        joinedload(EventRegistration.certificate),
    ).filter_by(instance_id=instance.id).order_by(
        EventRegistration.created_at.desc()
    ).all()

    return render_template(
        'admin/instance_registrations.html',
        instance=instance,
        registrations=registrations,
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
                f'Сертифікат {cert_number} видано. Email не відправлено -- '
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


@admin_bp.route('/registrations')
@admin_required
def registrations_all():
    status_filter = request.args.get('status', '')
    payment_filter = request.args.get('payment', '')
    method_filter = request.args.get('payment_method', '')
    instance_id_filter = request.args.get('instance_id', type=int)
    course_id_filter = request.args.get('course_id', type=int)
    trainer_id_filter = request.args.get('trainer_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    # Швидкий фільтр за часом заходу. За замовчуванням -- лише майбутні заходи,
    # щоб не показувати тисячі нерелевантних реєстрацій на минулі події.
    scope = request.args.get('scope', 'upcoming')
    if scope not in ('upcoming', 'past', 'all'):
        scope = 'upcoming'

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

    query = EventRegistration.query.options(
        joinedload(EventRegistration.user),
        joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
        joinedload(EventRegistration.certificate),
    )
    if status_filter and status_filter in dict(EventRegistration.STATUSES):
        query = query.filter(EventRegistration.status == status_filter)
    if payment_filter and payment_filter in dict(EventRegistration.PAYMENT_STATUSES):
        query = query.filter(EventRegistration.payment_status == payment_filter)
    if method_filter and method_filter in dict(EventRegistration.PAYMENT_METHODS):
        query = query.filter(EventRegistration.payment_method == method_filter)
    if instance_id_filter:
        query = query.filter(EventRegistration.instance_id == instance_id_filter)

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

    pagination = query.order_by(EventRegistration.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False,
    )

    instances = db.session.query(CourseInstance).options(
        joinedload(CourseInstance.course),
    ).order_by(CourseInstance.start_date.desc()).all()

    courses = db.session.query(Course).order_by(Course.title).all()
    trainers = db.session.query(Trainer).order_by(Trainer.full_name).all()

    return render_template(
        'admin/registrations.html',
        registrations=pagination.items,
        pagination=pagination,
        stats=stats,
        instances=instances,
        courses=courses,
        trainers=trainers,
        filters={
            'status': status_filter,
            'payment': payment_filter,
            'payment_method': method_filter,
            'instance_id': instance_id_filter,
            'course_id': course_id_filter,
            'trainer_id': trainer_id_filter,
            'scope': scope,
            'per_page': per_page,
        },
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
