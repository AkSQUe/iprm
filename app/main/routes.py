from flask import abort, flash, make_response, redirect, render_template, request, url_for
from flask_babel import gettext as _
from sqlalchemy.orm import joinedload

from app.extensions import csrf, db, limiter
from app.main import main_bp
from app.main.forms import ContactForm
from app.models.course import Course
from app.services.recaptcha import verify_request as verify_recaptcha


@main_bp.route('/')
def index():
    """Головна сторінка. Каталог курсів живе окремо на /courses
    (courses.course_list) -- редіректу більше немає. Збір даних -- у
    home_service (SRP); статистика кешується коротким TTL."""
    from app.services.home_service import home_context
    return render_template('main/home.html', active_nav='home', **home_context())


@main_bp.route('/materials/<token>', localize=False)
@limiter.limit('60 per minute')
def trainer_materials(token):
    """Public read-only view of an event's reserved materials, opened by trainers
    via a signed link (no login). 404 on a bad/unknown token or no reservation."""
    from app.main.forms import TrainerConfirmForm
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
    form = TrainerConfirmForm(comment=reservation.trainer_comment)
    return render_template('materials_trainer.html',
                           instance=instance, reservation=reservation, form=form,
                           token=token)


@main_bp.route('/materials/<token>/confirm', methods=['POST'], localize=False)
@limiter.limit('60 per minute')
def trainer_materials_confirm(token):
    """Trainer confirms the prepared kit (or leaves a comment about what's
    missing -- see app/main/forms.py:TrainerConfirmForm). One action, not two:
    confirmation always happens, the comment is free text beside it. Same
    signed token as the read-only page, no login. Re-confirming (a trainer
    adding a clarification later) updates the comment in place rather than
    erroring or duplicating the confirmation timestamp."""
    from app.main.forms import TrainerConfirmForm
    from app.services import material_reservation_service as mrs
    from app.models.material_reservation import MaterialReservation

    instance_id = mrs.load_trainer_token(token)
    if instance_id is None:
        abort(404)
    reservation = MaterialReservation.query.filter_by(instance_id=instance_id).first()
    if reservation is None:
        abort(404)

    form = TrainerConfirmForm()
    if form.validate_on_submit():
        mrs.confirm_reservation(reservation, form.comment.data)
        flash(_('Дякуємо! Ваше підтвердження отримано.'), 'success')
    return redirect(url_for('main.trainer_materials', token=token))


@main_bp.route('/r/<token>', localize=False)
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


@main_bp.route('/account')
def legacy_account():
    """Старе посилання на кабінет з листів про сертифікат -> /auth/account.

    Шаблон листа склеював адресу як `website_url ~ "/account"`, хоч кабінет
    завжди жив на `/auth/account`. Сам шаблон уже виправлено, але виправлення
    лікує ЛИШЕ майбутні листи: ті, що вже пішли людям, лежать у поштах із
    непрацездатним посиланням назавжди. Тож редирект тут -- єдиний спосіб
    зробити їх робочими.

    301, а не 302: адреса помилкова остаточно, і пошукові системи чи клієнти
    можуть її запам'ятати.
    """
    return redirect(url_for('auth.account'), code=301)


@main_bp.route('/labs')
def labs():
    courses = Course.query.options(
        joinedload(Course.trainer),
    ).filter(Course.is_active.is_(True)).order_by(Course.title).limit(6).all()
    return render_template('main/index.html', active_nav='labs', courses=courses)


@main_bp.route('/offer', localize=False)
def offer():
    return render_template('main/offer.html')


@main_bp.route('/offer/pdf', localize=False)
@limiter.limit('20 per minute')
def offer_pdf():
    """Підписана PDF-версія оферти (бланк, печатка, підпис).

    Рендериться на льоту з того самого партіала, що й сторінка, тому файл не
    може розійтися з чинною редакцією на сайті."""
    import io

    from flask import send_file

    from app.services.legal_pdf_service import (
        DOWNLOAD_NAME, LegalPdfError, render_offer_pdf,
    )

    try:
        pdf = render_offer_pdf()
    except LegalPdfError:
        flash(_('Не вдалося сформувати PDF. Спробуйте пізніше.'), 'error')
        return redirect(url_for('main.offer'))

    return send_file(
        io.BytesIO(pdf),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=DOWNLOAD_NAME,
    )


@main_bp.route('/privacy', localize=False)
def privacy():
    return render_template('main/privacy.html')


@main_bp.route('/refund', localize=False)
def refund():
    return render_template('main/refund.html')


@main_bp.route('/disclaimer', localize=False)
def disclaimer():
    return render_template('main/disclaimer.html')


@main_bp.route('/cookies', localize=False)
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
            flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
            return render_template('main/contact.html', form=form, active_nav='contact')
        flash(
            _('Дякуємо за ваше повідомлення! Ми зв\'яжемося з вами найближчим часом.'),
            'success',
        )
        return redirect(url_for('main.contact'))
    return render_template('main/contact.html', form=form, active_nav='contact')


@main_bp.route('/unsubscribe/<token>', methods=['GET', 'POST'], localize=False)
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


@main_bp.route('/design-system', localize=False)
def design_system():
    return render_template('design_system/index.html')


@main_bp.route('/set-lang/<lang>', localize=False)
def set_lang(lang):
    """Перемикання мови для сторінок без мовного префікса (admin, payments,
    сторінки помилок): зберігає вибір у session і повертає на next.
    Для локалізованих сторінок перемикач лінкує напряму на /ru|/en-URL
    (див. app/i18n.py:_switch_link). Параметр названо lang, а НЕ lang_code:
    app-рівневий url_value_preprocessor вилучає lang_code з view_args."""
    from flask import session
    from app.i18n import LANGUAGES
    if lang not in LANGUAGES:
        abort(404)
    session['lang'] = lang
    next_url = request.args.get('next', '')
    if not next_url.startswith('/') or next_url.startswith('//') or '\\' in next_url:
        next_url = url_for('main.index')
    return redirect(next_url)


@main_bp.route('/sitemap-page')
def sitemap_page():
    from app.services.sitemap_service import generate_visual_sitemap
    sections = generate_visual_sitemap()
    return render_template('main/sitemap.html', sections=sections, active_nav='sitemap')


@main_bp.route('/robots.txt', localize=False)
def robots():
    from app.i18n import PREFIXED_LANGUAGES
    private_paths = ['/auth/', '/registration/', '/payments/']
    # Приватні розділи мають дзеркала з мовним префіксом (/ru/auth/ ...).
    disallow = private_paths + [
        f'/{lang}{path}' for lang in PREFIXED_LANGUAGES for path in private_paths
    ]
    lines = [
        'User-agent: *',
        'Allow: /',
        '',
        'Disallow: /admin/',
        *[f'Disallow: {path}' for path in disallow],
        'Disallow: /design-system',
        '',
        f'Sitemap: {url_for("main.sitemap", _external=True)}',
    ]
    resp = make_response('\n'.join(lines))
    resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return resp


@main_bp.route('/sitemap.xml', localize=False)
def sitemap():
    from app.services.sitemap_service import generate_pages
    pages = generate_pages()
    resp = make_response(render_template('sitemap.xml', pages=pages))
    resp.headers['Content-Type'] = 'application/xml; charset=utf-8'
    # Боти не повинні бити БД щохвилини -- 1 година кешу в CDN/browser.
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp
