from flask import render_template, make_response, url_for
from sqlalchemy.orm import joinedload

from app.main import main_bp
from app.models.event import Event
from app.models.trainer import Trainer


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


@main_bp.route('/robots.txt')
def robots():
    lines = [
        'User-agent: *',
        'Allow: /',
        '',
        'Disallow: /auth/',
        'Disallow: /admin/',
        'Disallow: /registration/',
        'Disallow: /payments/',
        'Disallow: /design-system',
        '',
        f'Sitemap: {url_for("main.sitemap", _external=True)}',
    ]
    resp = make_response('\n'.join(lines))
    resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return resp


@main_bp.route('/sitemap.xml')
def sitemap():
    from app.models.trainer import Trainer

    pages = []

    from app.models.clinic import Clinic

    static_urls = [
        ('main.index', '1.0', 'weekly'),
        ('courses.course_list', '0.9', 'weekly'),
        ('trainers.trainer_list', '0.8', 'weekly'),
        ('clinics.clinic_list', '0.8', 'monthly'),
        ('main.offer', '0.3', 'yearly'),
        ('main.privacy', '0.3', 'yearly'),
        ('main.refund', '0.3', 'yearly'),
        ('main.disclaimer', '0.3', 'yearly'),
        ('main.cookies', '0.3', 'yearly'),
    ]
    for endpoint, priority, freq in static_urls:
        pages.append({
            'loc': url_for(endpoint, _external=True),
            'priority': priority,
            'changefreq': freq,
        })

    events = Event.query.filter(
        Event.is_active.is_(True),
        Event.status.in_(['published', 'active']),
    ).all()
    for event in events:
        pages.append({
            'loc': url_for('courses.course_by_slug', slug=event.slug, _external=True),
            'priority': '0.8',
            'changefreq': 'weekly',
            'lastmod': event.updated_at.strftime('%Y-%m-%d') if event.updated_at else None,
        })

    trainers = Trainer.query.filter_by(is_active=True).all()
    for trainer in trainers:
        pages.append({
            'loc': url_for('trainers.trainer_detail', slug=trainer.slug, _external=True),
            'priority': '0.6',
            'changefreq': 'monthly',
        })

    clinics = Clinic.query.filter_by(is_active=True).all()
    for clinic in clinics:
        pages.append({
            'loc': url_for('clinics.clinic_detail', slug=clinic.slug, _external=True),
            'priority': '0.6',
            'changefreq': 'monthly',
        })

    resp = make_response(render_template('sitemap.xml', pages=pages))
    resp.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return resp
