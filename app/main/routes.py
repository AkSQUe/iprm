from flask import abort, flash, make_response, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload

from app.extensions import csrf, db, limiter
from app.main import main_bp
from app.main.forms import ContactForm
from app.models.course import Course
from app.services.recaptcha import verify_request as verify_recaptcha


@main_bp.route('/')
def index():
    return redirect(url_for('courses.course_list'), code=301)


@main_bp.route('/materials/<token>')
@limiter.limit('60 per minute')
def trainer_materials(token):
    """Public read-only view of an event's reserved materials, opened by trainers
    via a signed link (no login). 404 on a bad/unknown token or no reservation."""
    from app.services import material_reservation_service as mrs
    from app.models.course_instance import CourseInstance
    from app.models.material_reservation import MaterialReservation

    instance_id = mrs.load_trainer_token(token)
    if instance_id is None:
        abort(404)
    instance = db.session.get(CourseInstance, instance_id)
    reservation = MaterialReservation.query.filter_by(instance_id=instance_id).first()
    if instance is None or reservation is None:
        abort(404)
    return render_template('materials_trainer.html',
                           instance=instance, reservation=reservation)


@main_bp.route('/r/<token>')
@limiter.limit('60 per minute')
def referrer_dashboard(token):
    """Публічний кабінет реферера за підписаним токеном (тренери без логіну):
    посилання, QR, баланс, історія нарахувань. 404 на битий токен."""
    from app.services import referral_service
    from app.models.site_settings import SiteSettings
    from app.models.trainer import Trainer
    from app.models.user import User

    if not SiteSettings.get().referral_enabled:
        abort(404)
    kind, referrer_id = referral_service.load_referrer_token(token)
    if kind is None:
        abort(404)

    if kind == 'trainer':
        referrer = db.session.get(Trainer, referrer_id)
        name = referrer.full_name if referrer else None
        link = referral_service.trainer_referral_link(referrer) if referrer else None
    else:
        referrer = db.session.get(User, referrer_id)
        name = (referrer.full_name or referrer.email) if referrer else None
        link = referral_service.user_referral_link(referrer) if referrer else None
    if referrer is None:
        abort(404)
    db.session.commit()  # можливо згенерувався код

    return render_template(
        'referrer_dashboard.html',
        referrer_name=name,
        link=link,
        qr=referral_service.qr_svg(link),
        balance=referral_service.get_balance(kind, referrer_id),
        pending=referral_service.get_pending_balance(kind, referrer_id),
        rewards=referral_service.list_referrer_rewards(kind, referrer_id, limit=100),
    )


@main_bp.route('/labs')
def labs():
    courses = Course.query.options(
        joinedload(Course.trainer),
    ).filter(Course.is_active.is_(True)).order_by(Course.title).limit(6).all()
    return render_template('main/index.html', active_nav='labs', courses=courses)


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


@main_bp.route('/bpr-documents')
def bpr_documents():
    """Окрема сторінка зі списком документів БПР (Положення про оцінку,
    методологія, конфлікт інтересів, тощо). Файли в app/static/bpr-documents/.
    """
    return render_template('main/bpr_documents.html', active_nav='bpr_documents')


@main_bp.route('/contact', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=['POST'])
def contact():
    form = ContactForm()
    if form.validate_on_submit():
        if not verify_recaptcha(action='contact'):
            flash('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.', 'error')
            return render_template('main/contact.html', form=form, active_nav='contact')
        flash(
            'Дякуємо за ваше повідомлення! Ми зв\'яжемося з вами найближчим часом.',
            'success',
        )
        return redirect(url_for('main.contact'))
    return render_template('main/contact.html', form=form, active_nav='contact')


@main_bp.route('/unsubscribe/<token>', methods=['GET', 'POST'])
@csrf.exempt  # List-Unsubscribe-Post робить машинний POST без CSRF-токена
def unsubscribe(token):
    """Відписка від НЕОБОВ'ЯЗКОВИХ листів (нагадування). Транзакційні
    (пароль, підтвердження email) шлються завжди -- це не зачіпається.

    GET  -- сторінка з поточним станом і кнопкою.
    POST -- one-click (RFC 8058): будь-який POST = відписка; action=resubscribe
            повертає підписку. CSRF-exempt, бо поштовий клієнт шле без токена.
    """
    from app.models.user import User
    user = User.query.filter_by(unsubscribe_token=token).first()
    if user is None:
        return render_template('main/unsubscribe.html', user=None, done=False), 404
    if request.method == 'POST':
        user.email_opt_out = request.form.get('action') != 'resubscribe'
        db.session.commit()
        return render_template('main/unsubscribe.html', user=user, done=True)
    return render_template('main/unsubscribe.html', user=user, done=False)


@main_bp.route('/design-system')
def design_system():
    return render_template('design_system/index.html')


@main_bp.route('/sitemap-page')
def sitemap_page():
    from app.services.sitemap_service import generate_visual_sitemap
    sections = generate_visual_sitemap()
    return render_template('main/sitemap.html', sections=sections, active_nav='sitemap')


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
    # Боти не повинні бити БД щохвилини -- 1 година кешу в CDN/browser.
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp
