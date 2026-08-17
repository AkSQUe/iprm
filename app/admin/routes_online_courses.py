"""Адмінка: каталог онлайн-курсів (дзеркало Sintegrum).

GET  /admin/online-courses                  -- УВЕСЬ перелік із дзеркала
GET  /admin/online-courses/<id>             -- редагування наших полів
POST /admin/online-courses/<id>             -- збереження
POST /admin/online-courses/<id>/publish     -- перемикач публікації

Показуємо всі курси, включно з неактивними в Sintegrum і зниклими: адмін
має бачити повну картину того, що є на тому боці, і сам вирішувати, що
виносити на сайт. Публічний каталог показує лише опубліковані.

Тут редагуються ЛИШЕ наші поля. Дані Sintegrum (remote_*) віддаються в
шаблон для читання: їх перезаписує синхронізація, і будь-яке редагування
тут було б стерте наступним прогоном.
"""
import logging
from decimal import Decimal, InvalidOperation

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.admin._helpers import try_commit
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.online_course import OnlineCourse
from app.models.site_settings import SiteSettings
from app.services.online_course_sync import generate_unique_slug

audit_logger = logging.getLogger('audit')

PER_PAGE = 30

STATUS_OPTIONS = [
    ('published', 'Опубліковані'),
    ('hidden', 'Приховані'),
    ('ready', 'Готові до публікації'),
    ('incomplete', 'Не готові (немає ціни чи посилання)'),
    ('vanished', 'Зниклі з Sintegrum'),
]


@admin_bp.route('/online-courses')
@admin_required
def online_courses_list():
    filters = {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', [key for key, _ in STATUS_OPTIONS]),
    }

    query = OnlineCourse.query
    query = _listing.apply_search(
        query, filters['q'], [OnlineCourse.remote_name, OnlineCourse.title,
                              OnlineCourse.slug],
    )

    status = filters['status']
    if status == 'published':
        query = query.filter(OnlineCourse.is_published.is_(True))
    elif status == 'hidden':
        query = query.filter(OnlineCourse.is_published.is_(False))
    elif status == 'vanished':
        query = query.filter(OnlineCourse.is_vanished.is_(True))
    elif status == 'ready':
        query = query.filter(
            OnlineCourse.is_vanished.is_(False),
            OnlineCourse.access_url.isnot(None),
            OnlineCourse.access_url != '',
            OnlineCourse.price.isnot(None),
            OnlineCourse.price > 0,
        )
    elif status == 'incomplete':
        query = query.filter(db.or_(
            OnlineCourse.access_url.is_(None),
            OnlineCourse.access_url == '',
            OnlineCourse.price.is_(None),
            OnlineCourse.price <= 0,
        ))

    pagination = query.order_by(
        OnlineCourse.is_vanished,
        OnlineCourse.sort_order,
        OnlineCourse.remote_name,
    ).paginate(
        page=request.args.get('page', 1, type=int),
        per_page=PER_PAGE, error_out=False,
    )
    courses = pagination.items

    settings = SiteSettings.get()
    return render_template(
        'admin/online_courses.html',
        courses=courses,
        pagination=pagination,
        filter_args=_listing.filter_args(filters),
        filters=filters,
        status_options=STATUS_OPTIONS,
        integration_enabled=settings.sintegrum_enabled,
        last_sync_at=settings.sintegrum_last_sync_at,
        totals={
            'all': OnlineCourse.query.count(),
            'published': OnlineCourse.query.filter_by(is_published=True).count(),
            'vanished': OnlineCourse.query.filter_by(is_vanished=True).count(),
        },
    )


@admin_bp.route('/online-courses/<int:course_id>', methods=['GET', 'POST'])
@admin_required
def online_course_edit(course_id):
    course = db.session.get(OnlineCourse, course_id)
    if course is None:
        flash('Курс не знайдено', 'error')
        return redirect(url_for('admin.online_courses_list'))

    if request.method == 'POST':
        return _save_course(course)

    from app.models.trainer import Trainer
    from app.services import course_service

    return render_template(
        'admin/online_course_edit.html',
        course=course,
        trainer_options=Trainer.query.order_by(Trainer.full_name).all(),
        # Текстові представлення JSON-полів. Рахуємо тут, а не в шаблоні:
        # формати введення спільні з формою офлайнового курсу, і правило
        # їх розбору має жити в одному місці.
        proof_stats_text=course_service.pairs_list_to_text(course.proof_stats),
        benefits_text=course_service.blocks_list_to_text(
            course.benefits, 'title', 'text'),
        target_audience_text=course_service.list_to_lines(course.target_audience),
        faq_text=course_service.faq_list_to_text(course.faq),
        gallery_json=course_service.gallery_to_json(course.gallery),
    )


def _parse_price(raw):
    raw = (raw or '').strip().replace(',', '.')
    if not raw:
        return None, None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None, 'Ціна: очікується число'
    if value < 0:
        return None, 'Ціна не може бути від\'ємною'
    return value, None


def _parse_positive_int(raw, label):
    raw = (raw or '').strip()
    if not raw:
        return None, None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f'{label}: очікується ціле число'
    if value <= 0:
        return None, f'{label}: має бути більше нуля'
    return value, None


def _save_course(course):
    price, err = _parse_price(request.form.get('price'))
    if err:
        flash(err, 'error')
        return redirect(url_for('admin.online_course_edit', course_id=course.id))

    duration, err = _parse_positive_int(
        request.form.get('duration_hours'), 'Тривалість',
    )
    if err:
        flash(err, 'error')
        return redirect(url_for('admin.online_course_edit', course_id=course.id))

    ttl, err = _parse_positive_int(
        request.form.get('access_ttl_hours'), 'Термін дії посилання',
    )
    if err:
        flash(err, 'error')
        return redirect(url_for('admin.online_course_edit', course_id=course.id))

    cpd, err = _parse_positive_int(request.form.get('cpd_points'), 'Бали БПР')
    if err:
        flash(err, 'error')
        return redirect(url_for('admin.online_course_edit', course_id=course.id))

    access_url = (request.form.get('access_url') or '').strip()
    if access_url and not access_url.startswith('https://'):
        flash('Посилання на навчання має починатися з https://', 'error')
        return redirect(url_for('admin.online_course_edit', course_id=course.id))

    slug = (request.form.get('slug') or '').strip()
    if slug and slug != course.slug:
        taken = OnlineCourse.query.filter(
            OnlineCourse.slug == slug, OnlineCourse.id != course.id,
        ).first()
        if taken:
            flash(f'Адреса «{slug}» уже зайнята іншим курсом', 'error')
            return redirect(url_for('admin.online_course_edit', course_id=course.id))
        course.slug = slug
    elif not slug:
        course.slug = generate_unique_slug(course.remote_name, exclude_id=course.id)

    course.title = (request.form.get('title') or '').strip() or None
    course.description = (request.form.get('description') or '').strip() or None
    course.short_description = (
        request.form.get('short_description') or '').strip() or None
    course.price = price
    course.duration_hours = duration
    course.cpd_points = cpd
    course.access_url = access_url or None
    course.access_ttl_hours = ttl
    course.is_featured = request.form.get('is_featured') == 'on'

    # --- Контент продажної сторінки. Ті самі формати введення, що й у курсу
    #     офлайн: онлайн- і офлайн-сторінка зібрані з тих самих партіалів,
    #     тож і редактор має поводитись однаково. ---
    from app.services import course_service

    course.final_cta_text = (
        request.form.get('final_cta_text') or '').strip() or None
    course.practice_note_title = (
        request.form.get('practice_note_title') or '').strip() or None
    course.practice_note_text = (
        request.form.get('practice_note_text') or '').strip() or None
    course.gallery_intro = (
        request.form.get('gallery_intro') or '').strip() or None
    course.target_audience = course_service.lines_to_list(
        request.form.get('target_audience_text'))
    course.faq = course_service.faq_text_to_list(request.form.get('faq_text'))
    course.proof_stats = course_service.pairs_text_to_list(
        request.form.get('proof_stats_text'))
    course.benefits = course_service.blocks_text_to_list(
        request.form.get('benefits_text'), 'title', 'text')

    try:
        course.trainer_id = int(request.form.get('trainer_id') or 0) or None
    except (TypeError, ValueError):
        course.trainer_id = None

    try:
        course.sort_order = int(request.form.get('sort_order') or 0)
    except (TypeError, ValueError):
        course.sort_order = 0

    # Той самий хелпер, що й у решті адмін-форм: він читає поля вигляду
    # `<field>_<lang>`, які кладуть мовні вкладки, і сам знає про JSON-поля.
    from app.admin.routes_translations import apply_inline_translations
    apply_inline_translations(course)

    # Публікація живе тут же, але лише якщо курс до неї готовий. Перевірка
    # саме на сервері: інакше опублікувати непридатний курс можна було б
    # звичайним POST-ом в обхід форми.
    wants_published = request.form.get('is_published') == 'on'
    if wants_published and not course.can_be_published:
        course.is_published = False
        flash(
            'Курс збережено, але опублікувати не вдалося: бракує '
            + ', '.join(course.missing_for_publication),
            'warning',
        )
    else:
        course.is_published = wants_published

    # Блоки програми й галерея -- після решти полів: обидва пишуть у сесію і
    # потребують валідного course.slug (той міг щойно змінитись).
    blocks = course_service.extract_program_blocks_from_form(request.form)
    course_service.save_program_blocks_for_online_course(course, blocks)
    course_service.save_gallery(
        course,
        course_service.parse_gallery_entries(request.form.get('gallery_json')),
        entity_type='online_course',
    )

    if try_commit(log_context=f'online course {course.id}'):
        audit_logger.info(
            'Admin %s updated online course %s (sintegrum_id=%s, published=%s)',
            current_user.email, course.id, course.sintegrum_id, course.is_published,
        )
        flash('Курс збережено', 'success')

    return redirect(url_for('admin.online_course_edit', course_id=course.id))


@admin_bp.route('/online-courses/<int:course_id>/publish', methods=['POST'])
@admin_required
def online_course_toggle_publish(course_id):
    course = db.session.get(OnlineCourse, course_id)
    if course is None:
        flash('Курс не знайдено', 'error')
        return redirect(url_for('admin.online_courses_list'))

    if course.is_published:
        course.is_published = False
        message = f'Курс «{course.effective_title}» знято з публікації'
    else:
        if not course.can_be_published:
            flash(
                'Не можна опублікувати: бракує '
                + ', '.join(course.missing_for_publication),
                'error',
            )
            return redirect(url_for('admin.online_courses_list'))
        course.is_published = True
        message = f'Курс «{course.effective_title}» опубліковано'

    if try_commit(log_context=f'online course publish {course.id}'):
        audit_logger.info(
            'Admin %s set online course %s published=%s',
            current_user.email, course.id, course.is_published,
        )
        flash(message, 'success')

    return redirect(url_for('admin.online_courses_list'))
