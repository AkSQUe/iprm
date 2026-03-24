from flask import render_template
from sqlalchemy.orm import joinedload

from app.main import main_bp
from app.models.event import Event


@main_bp.route('/')
def index():
    events = Event.query.options(
        joinedload(Event.trainer),
    ).filter(
        Event.is_active.is_(True),
        Event.status.in_(['published', 'active']),
    ).order_by(Event.start_date).limit(6).all()
    return render_template('main/index.html', active_nav='labs', events=events)


@main_bp.route('/offer')
def offer():
    return render_template('main/offer.html')


@main_bp.route('/privacy')
def privacy():
    return render_template('main/privacy.html')


@main_bp.route('/refund')
def refund():
    return render_template('main/refund.html')


@main_bp.route('/disclaimer')
def disclaimer():
    return render_template('main/disclaimer.html')


@main_bp.route('/cookies')
def cookies():
    return render_template('main/cookies.html')


@main_bp.route('/design-system')
def design_system():
    return render_template('design_system/index.html')
