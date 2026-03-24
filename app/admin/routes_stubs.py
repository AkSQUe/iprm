import logging
from flask import render_template, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.registration import EventRegistration

audit_logger = logging.getLogger('audit')


@admin_bp.route('/')
@admin_required
def dashboard():
    return redirect(url_for('admin.events_list'))


@admin_bp.route('/payments')
@admin_required
def payments():
    return redirect(url_for('admin.liqpay'))


@admin_bp.route('/liqpay')
@admin_required
def liqpay():
    from sqlalchemy import func as sa_func
    from app.services.liqpay import get_liqpay_service

    service = get_liqpay_service()
    cfg = {
        'public_key': _mask_key(service.public_key),
        'private_key': _mask_key(service.private_key),
        'sandbox': service.sandbox,
        'is_configured': service.is_configured,
        'webhook_url': url_for('payments.liqpay_callback', _external=True),
    }

    stats = db.session.query(
        sa_func.count(EventRegistration.id).label('total'),
        sa_func.count(EventRegistration.id).filter(
            EventRegistration.payment_status == 'paid'
        ).label('paid'),
        sa_func.count(EventRegistration.id).filter(
            EventRegistration.payment_status == 'pending'
        ).label('pending'),
        sa_func.count(EventRegistration.id).filter(
            EventRegistration.payment_status == 'refunded'
        ).label('refunded'),
        sa_func.coalesce(sa_func.sum(
            EventRegistration.payment_amount
        ).filter(EventRegistration.payment_status == 'paid'), 0).label('total_amount'),
    ).filter(
        EventRegistration.payment_amount > 0,
    ).one()

    recent = EventRegistration.query.options(
        joinedload(EventRegistration.event),
        joinedload(EventRegistration.user),
    ).filter(
        EventRegistration.payment_amount > 0,
    ).order_by(EventRegistration.created_at.desc()).limit(20).all()

    return render_template(
        'admin/liqpay.html',
        cfg=cfg,
        stats=stats,
        recent=recent,
    )


def _mask_key(key):
    if not key:
        return ''
    if len(key) <= 4:
        return '****'
    return '****' + key[-4:]


@admin_bp.route('/certificates')
@admin_required
def certificates():
    return render_template(
        'admin/stub.html',
        admin_section='certificates',
        page_title='Сертифікати',
        page_subtitle='Управління сертифікатами слухачів',
    )


@admin_bp.route('/users')
@admin_required
def users():
    from app.models.user import User
    reg_count = User.with_registration_count()
    rows = db.session.query(User, reg_count).order_by(User.created_at.desc()).all()

    all_users = []
    for user, count in rows:
        user._cached_reg_count = count
        all_users.append(user)

    return render_template('admin/users.html', users=all_users)


@admin_bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def toggle_admin(user_id):
    from app.models.user import User
    user = db.session.get(User, user_id)
    if not user:
        flash('Користувача не знайдено', 'error')
        return redirect(url_for('admin.users'))
    if user.id == current_user.id:
        flash('Неможливо змінити власні повноваження', 'error')
        return redirect(url_for('admin.users'))
    user.is_admin = not user.is_admin
    try:
        db.session.commit()
        status = 'надано' if user.is_admin else 'знято'
        audit_logger.info('Admin %s toggled admin for user %s (%s): %s',
                          current_user.email, user.id, user.email, status)
        flash(f'Адмін-повноваження {status}: {user.email}', 'success')
    except Exception:
        db.session.rollback()
        flash('Помилка при оновленні', 'error')
    return redirect(url_for('admin.users'))


@admin_bp.route('/reviews')
@admin_required
def reviews():
    return render_template(
        'admin/stub.html',
        admin_section='reviews',
        page_title='Відгуки',
        page_subtitle='Відгуки учасників на заходи',
    )


@admin_bp.route('/marketing')
@admin_required
def marketing():
    return render_template('admin/marketing.html')


@admin_bp.route('/integrations')
@admin_required
def integrations():
    return render_template('admin/integrations.html')


@admin_bp.route('/settings')
@admin_required
def settings():
    return render_template(
        'admin/stub.html',
        admin_section='settings',
        page_title='Налаштування',
        page_subtitle='Загальні налаштування системи',
    )
