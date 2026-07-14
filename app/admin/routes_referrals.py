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

    # Зведення: активні/анульовані нарахування, сума активних балів.
    stats = db.session.query(
        func.count().label('total'),
        func.count(case((ReferralReward.status == 'granted', 1))).label('granted'),
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
    top_referrers = [{
        'kind': r.referrer_kind,
        'id': r.referrer_id,
        'balance': int(r.balance or 0),
        'rewards': r.rewards,
        'info': name_map.get(r.code),
    } for r in top_rows]

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

    return render_template(
        'admin/referrals.html',
        settings=settings,
        stats=stats,
        top_referrers=top_referrers,
        rewards=pagination.items,
        pagination=pagination,
        referrer_map=page_name_map,
        status_filter=status_filter,
    )


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
