"""Адмін-огляд реферальної програми: зведення, топ-реферери, історія нарахувань.

Лише читання. Нарахування/анулювання відбуваються автоматично при зміні
статусу оплати (див. referral_service.sync_reward_for_registration).
"""
import logging

from flask import render_template, request, send_file
from sqlalchemy import case, func
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.referral_reward import ReferralReward
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.services import referral_service

logger = logging.getLogger(__name__)


@admin_bp.route('/referrals')
@admin_required
def referrals_overview():
    settings = SiteSettings.get()
    status_filter = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Зведення: активні/очікують/анульовані нарахування, сума активних балів.
    stats = db.session.query(
        func.count().label('total'),
        func.count(case((ReferralReward.status == 'granted', 1))).label('granted'),
        func.count(case((ReferralReward.status == 'pending', 1))).label('pending'),
        func.count(case((ReferralReward.status == 'voided', 1))).label('voided'),
        func.coalesce(
            func.sum(case((ReferralReward.status == 'granted', ReferralReward.points), else_=0)),
            0,
        ).label('granted_points'),
    ).one()

    # Топ-реферери за активним балансом (сума granted-балів). Код реферера
    # стабільний -> беремо max() у GROUP BY (уникаємо N+1 на резолв).
    top_rows = db.session.query(
        ReferralReward.referrer_kind,
        ReferralReward.referrer_id,
        func.max(ReferralReward.referral_code).label('code'),
        func.sum(ReferralReward.points).label('balance'),
        func.count().label('rewards'),
    ).filter(
        ReferralReward.status == 'granted',
    ).group_by(
        ReferralReward.referrer_kind, ReferralReward.referrer_id,
    ).order_by(func.sum(ReferralReward.points).desc()).limit(20).all()

    name_map = referral_service.resolve_referrers_bulk([r.code for r in top_rows])
    clicks_map = referral_service.get_clicks_by_code([r.code for r in top_rows])
    top_referrers = [{
        'kind': r.referrer_kind,
        'id': r.referrer_id,
        'balance': int(r.balance or 0),
        'rewards': r.rewards,
        'clicks': clicks_map.get(r.code, 0),
        'info': name_map.get(r.code),
    } for r in top_rows]

    # Воронка: усього кліків + приведені-але-неоплачені реєстрації (pipeline).
    from app.models.referral_click import ReferralClick
    total_clicks = int(db.session.query(
        func.coalesce(func.sum(ReferralClick.count), 0)).scalar() or 0)
    pipeline_count = db.session.query(func.count(EventRegistration.id)).filter(
        EventRegistration.referral_code.isnot(None),
        EventRegistration.payment_status != 'paid',
        EventRegistration.status != 'cancelled',
    ).scalar()

    # Історія нарахувань (з реєстрацією/курсом для контексту).
    query = ReferralReward.query.options(
        joinedload(ReferralReward.registration)
        .joinedload(EventRegistration.instance)
        .joinedload(CourseInstance.course),
        joinedload(ReferralReward.registration)
        .joinedload(EventRegistration.user),
    )
    if status_filter in ('granted', 'voided'):
        query = query.filter(ReferralReward.status == status_filter)
    pagination = query.order_by(ReferralReward.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False,
    )

    # Імена рефереров для сторінки історії.
    page_codes = [r.referral_code for r in pagination.items]
    page_name_map = referral_service.resolve_referrers_bulk(page_codes)

    fraud = referral_service.fraud_flags()

    return render_template(
        'admin/referrals.html',
        settings=settings,
        stats=stats,
        top_referrers=top_referrers,
        total_clicks=total_clicks,
        pipeline_count=pipeline_count,
        fraud=fraud,
        rewards=pagination.items,
        pagination=pagination,
        referrer_map=page_name_map,
        status_filter=status_filter,
    )


@admin_bp.route('/referrals/<kind>/<int:referrer_id>')
@admin_required
def referral_referrer_detail(kind, referrer_id):
    """Деталізація одного реферера: профіль, баланс, повна історія нарахувань."""
    from flask import abort
    from app.models.user import User
    from app.models.trainer import Trainer

    if kind not in ('user', 'trainer'):
        abort(404)
    if kind == 'user':
        referrer = db.session.get(User, referrer_id)
        name = (referrer.full_name or referrer.email) if referrer else None
        edit_url = None
    else:
        referrer = db.session.get(Trainer, referrer_id)
        name = referrer.full_name if referrer else None
        edit_url = 'admin.trainer_edit'

    balance = referral_service.get_balance(kind, referrer_id)
    pending = referral_service.get_pending_balance(kind, referrer_id)
    rewards = referral_service.list_referrer_rewards(kind, referrer_id, limit=None)
    adjustments = referral_service.list_adjustments(kind, referrer_id)
    granted = sum(1 for r in rewards if r.status == 'granted')

    # Воронка реферера: кліки -> нарахування (конверсія).
    clicks = referral_service.get_clicks_for_referrer(kind, referrer_id)
    conversions = sum(1 for r in rewards if r.status in ('granted', 'pending'))
    conversion_rate = round(conversions / clicks * 100, 1) if clicks else None

    return render_template(
        'admin/referral_detail.html',
        kind=kind, referrer_id=referrer_id, referrer=referrer,
        referrer_name=name, edit_url=edit_url,
        balance=balance, pending=pending, rewards=rewards,
        adjustments=adjustments, granted=granted,
        clicks=clicks, conversions=conversions, conversion_rate=conversion_rate,
    )


@admin_bp.route('/referrals/<kind>/<int:referrer_id>/adjust', methods=['POST'])
@admin_required
def referral_referrer_adjust(kind, referrer_id):
    """Ручна корекція балансу реферера (+/- балів із причиною)."""
    from flask import abort, flash, redirect, url_for
    from flask_login import current_user
    if kind not in ('user', 'trainer'):
        abort(404)
    try:
        points = int(request.form.get('points', '').strip())
    except (TypeError, ValueError):
        points = 0
    reason = (request.form.get('reason') or '').strip()
    if points == 0 or not reason:
        flash('Вкажіть ненульову кількість балів і причину', 'error')
        return redirect(url_for('admin.referral_referrer_detail',
                                kind=kind, referrer_id=referrer_id))
    referral_service.add_adjustment(
        kind, referrer_id, points, reason[:255], created_by_id=current_user.id,
    )
    flash(f'Баланс скориговано на {points:+d} балів', 'success')
    return redirect(url_for('admin.referral_referrer_detail',
                            kind=kind, referrer_id=referrer_id))


@admin_bp.route('/referrals/export')
@admin_required
def referrals_export():
    """Експорт усього реєстру нарахувань у xlsx (з опційним фільтром статусу)."""
    from app.services import xlsx_io
    status_filter = request.args.get('status', '')

    query = ReferralReward.query.options(
        joinedload(ReferralReward.registration)
        .joinedload(EventRegistration.instance)
        .joinedload(CourseInstance.course),
        joinedload(ReferralReward.registration)
        .joinedload(EventRegistration.user),
    )
    if status_filter in ('granted', 'voided'):
        query = query.filter(ReferralReward.status == status_filter)
    rewards = query.order_by(ReferralReward.created_at.desc()).all()

    name_map = referral_service.resolve_referrers_bulk(
        [r.referral_code for r in rewards],
    )
    buf = xlsx_io.export_referral_rewards_xlsx(rewards, name_map)
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='referral-rewards.xlsx',
    )
