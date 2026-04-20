from datetime import datetime, timezone

from flask import render_template, abort, redirect, url_for, request, flash
from sqlalchemy.orm import joinedload, selectinload

from app.courses import courses_bp
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_request import CourseRequest


@courses_bp.route('/')
def course_list():
    """Каталог: всі активні курси (навіть без запланованих проведень)."""
    courses = Course.query.options(
        joinedload(Course.trainer),
        selectinload(Course.instances),
    ).filter(Course.is_active.is_(True)).order_by(Course.title).all()

    now = datetime.now(timezone.utc)
    upcoming_by_course = {
        c.id: sorted(
            [i for i in c.instances
             if i.status in ('published', 'active')
             and (i.start_date is None or i.start_date >= now)],
            key=lambda i: i.start_date or datetime.max.replace(tzinfo=timezone.utc),
        )
        for c in courses
    }

    # Плоский список найближчих instances для секції "Графік"
    upcoming_instances = sorted(
        [i for c in courses for i in upcoming_by_course[c.id]],
        key=lambda i: i.start_date or datetime.max.replace(tzinfo=timezone.utc),
    )

    return render_template(
        'courses/list.html',
        active_nav='courses',
        courses=courses,
        upcoming_by_course=upcoming_by_course,
        upcoming_instances=upcoming_instances,
    )


@courses_bp.route('/<slug>')
def course_by_slug(slug):
    """Детальна сторінка курсу: контент Course + список проведень."""
    course = Course.query.options(
        joinedload(Course.trainer),
        selectinload(Course.instances).joinedload(CourseInstance.trainer),
        selectinload(Course.program_blocks),
    ).filter_by(slug=slug, is_active=True).first()

    if not course:
        abort(404)

    now = datetime.now(timezone.utc)
    upcoming_instances = sorted(
        [i for i in course.instances
         if i.status in ('published', 'active')
         and (i.start_date is None or i.start_date >= now)],
        key=lambda i: i.start_date or datetime.max.replace(tzinfo=timezone.utc),
    )
    past_instances = sorted(
        [i for i in course.instances
         if i.status == 'completed'
         or (i.start_date and i.start_date < now)],
        key=lambda i: i.start_date or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    return render_template(
        'courses/detail.html',
        active_nav='courses',
        course=course,
        upcoming_instances=upcoming_instances,
        past_instances=past_instances,
    )


@courses_bp.route('/<slug>/request', methods=['POST'])
def course_request(slug):
    """Клієнтський запит на проведення курсу (коли немає запланованих дат)."""
    course = Course.query.filter_by(slug=slug, is_active=True).first()
    if not course:
        abort(404)

    email = (request.form.get('email') or '').strip()
    phone = (request.form.get('phone') or '').strip() or None
    message = (request.form.get('message') or '').strip() or None

    if not email or '@' not in email:
        flash('Вкажіть валідний email', 'error')
        return redirect(url_for('courses.course_by_slug', slug=slug) + '#request')

    from flask_login import current_user
    user_id = current_user.id if current_user.is_authenticated else None

    req = CourseRequest(
        course_id=course.id,
        user_id=user_id,
        email=email,
        phone=phone,
        message=message,
        status='pending',
    )
    db.session.add(req)
    try:
        db.session.commit()
        flash('Дякуємо! Ми повідомимо вас коли буде запланована дата.', 'success')
    except Exception:
        db.session.rollback()
        flash('Помилка при надсиланні запиту. Спробуйте ще раз.', 'error')

    return redirect(url_for('courses.course_by_slug', slug=slug) + '#request-sent')


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
