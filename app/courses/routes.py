from flask import render_template, abort

from app.courses import courses_bp
from app.models.event import Event


@courses_bp.route('/courses')
def course_list():
    events = Event.query.filter(
        Event.is_active.is_(True),
        Event.status.in_(['published', 'active']),
    ).order_by(Event.start_date).all()
    return render_template('courses/list.html', active_nav='courses', events=events)


@courses_bp.route('/courses/<slug>')
def course_by_slug(slug):
    event = Event.query.filter_by(slug=slug, is_active=True).first()
    if not event:
        abort(404)
    return render_template('courses/event.html', event=event, active_nav='courses')


# Legacy hardcoded routes - fallback to static templates if no DB record
LEGACY_SLUGS = {
    'course_detail': 'plazmoterapiya-v-ginekologii',
    'course_stomatology': 'plazmoterapiya-v-stomatologii',
    'course_orthopedics': 'plazmoterapiya-v-ortopedii',
}

LEGACY_TEMPLATES = {
    'course_detail': 'courses/detail.html',
    'course_stomatology': 'courses/stomatology.html',
    'course_orthopedics': 'courses/orthopedics.html',
}


def _legacy_or_db(route_name):
    slug = LEGACY_SLUGS.get(route_name)
    if slug:
        event = Event.query.filter_by(slug=slug, is_active=True).first()
        if event:
            return render_template('courses/event.html', event=event, active_nav='courses')
    return render_template(LEGACY_TEMPLATES[route_name], active_nav='courses')


@courses_bp.route('/course-detail')
def course_detail():
    return _legacy_or_db('course_detail')


@courses_bp.route('/course-stomatology')
def course_stomatology():
    return _legacy_or_db('course_stomatology')


@courses_bp.route('/course-orthopedics')
def course_orthopedics():
    return _legacy_or_db('course_orthopedics')
