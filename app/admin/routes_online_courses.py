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
from app.i18n import PREFIXED_LANGUAGES
from app.models.online_course import OnlineCourse
from app.models.site_settings import SiteSettings
from app.services.online_course_sync import generate_unique_slug

audit_logger = logging.getLogger('audit')

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

    courses = query.order_by(
        OnlineCourse.is_vanished,
        OnlineCourse.sort_order,
        OnlineCourse.remote_name,
    ).all()

    settings = SiteSettings.get()
    return render_template(
        'admin/online_courses.html',
        courses=courses,
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

    return render_template(
        'admin/online_course_edit.html',
        course=course,
        languages=PREFIXED_LANGUAGES,
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

    try:
        course.sort_order = int(request.form.get('sort_order') or 0)
    except (TypeError, ValueError):
        course.sort_order = 0

    for lang in PREFIXED_LANGUAGES:
        for field in ('title', 'description', 'short_description'):
            value = (request.form.get(f'{field}_{lang}') or '').strip()
            course.set_translation(lang, field, value)

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
