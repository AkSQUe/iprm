from flask import render_template, abort, redirect, url_for
from sqlalchemy.orm import joinedload, selectinload

from app.courses import courses_bp
from app.models.event import Event


@courses_bp.route('/')
def course_list():
    events = Event.query.options(
        joinedload(Event.trainer),
    ).filter(
        Event.is_active.is_(True),
        Event.status.in_(['published', 'active', 'completed']),
    ).order_by(Event.start_date).all()
    return render_template('courses/list.html', active_nav='courses', events=events)


@courses_bp.route('/<slug>')
def course_by_slug(slug):
    event = Event.query.options(
        joinedload(Event.trainer),
        selectinload(Event.program_blocks),
    ).filter_by(slug=slug, is_active=True).first()
    if not event:
        abort(404)
    return render_template('courses/event.html', event=event, active_nav='courses')


# Legacy URL redirects -> slug-based routes
LEGACY_REDIRECTS = {
    'detail': 'plazmoterapiya-v-ginekologii',
    'stomatology': 'plazmoterapiya-v-stomatologii',
    'orthopedics': 'plazmoterapiya-v-ortopedii',
}


@courses_bp.route('/detail')
def course_detail():
    return redirect(url_for('courses.course_by_slug', slug=LEGACY_REDIRECTS['detail']), code=301)


@courses_bp.route('/stomatology')
def course_stomatology():
    return redirect(url_for('courses.course_by_slug', slug=LEGACY_REDIRECTS['stomatology']), code=301)


@courses_bp.route('/orthopedics')
def course_orthopedics():
    return redirect(url_for('courses.course_by_slug', slug=LEGACY_REDIRECTS['orthopedics']), code=301)
