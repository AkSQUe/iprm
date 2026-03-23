from flask import render_template

from app.main import main_bp
from app.models.event import Event


@main_bp.route('/')
def index():
    events = Event.query.filter(
        Event.is_active.is_(True),
        Event.status.in_(['published', 'active']),
    ).order_by(Event.start_date).limit(6).all()
    return render_template('main/index.html', active_nav='labs', events=events)


@main_bp.route('/design-system')
def design_system():
    return render_template('design_system/index.html')
