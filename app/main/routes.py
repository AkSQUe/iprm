from flask import flash, make_response, redirect, render_template, url_for
from sqlalchemy.orm import joinedload

from app.extensions import limiter
from app.main import main_bp
from app.main.forms import ContactForm
from app.models.event import Event
from app.models.trainer import Trainer


@main_bp.route('/')
def index():
    return redirect(url_for('courses.course_list'))


@main_bp.route('/labs')
def labs():
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


@main_bp.route('/contact', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=['POST'])
def contact():
    form = ContactForm()
    if form.validate_on_submit():
        flash(
            'Дякуємо за ваше повідомлення! Ми зв\'яжемося з вами найближчим часом.',
            'success',
        )
        return redirect(url_for('main.contact'))
    return render_template('main/contact.html', form=form, active_nav='contact')


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
    from app.services.sitemap_service import generate_pages
    pages = generate_pages()
    resp = make_response(render_template('sitemap.xml', pages=pages))
    resp.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return resp
