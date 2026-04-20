from datetime import datetime, timezone

from email_validator import EmailNotValidError, validate_email
from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload, selectinload

from app.courses import courses_bp
from app.extensions import db, limiter
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_request import CourseRequest
from app.models.registration import EventRegistration
from app.utils import ensure_utc
from sqlalchemy import func

# Обмеження довжини полів клієнтської форми "Запит на проведення".
_REQUEST_EMAIL_MAX = 254
_REQUEST_PHONE_MAX = 20
_REQUEST_MESSAGE_MAX = 2000

# Legacy URL redirects -> slug-based routes.
# Ключі -- історичні URL (стомали в email-розсилках і SERP), значення --
# цільовий slug у БД. Обробляються в course_by_slug перед запитом до БД.
LEGACY_REDIRECTS = {
    'detail': 'plazmoterapiya-v-ginekologii',
    'stomatology': 'plazmoterapiya-v-stomatologii',
    'orthopedics': 'plazmoterapiya-v-ortopedii',
}


def _open_instance_ids(course_ids):
    """Повертає set id CourseInstance.id, що відкриті для реєстрації.

    Агрегує `COUNT(*)` активних реєстрацій одним запитом замість N+1.
    """
    if not course_ids:
        return set()
    rows = (
        db.session.query(
            CourseInstance.id,
            CourseInstance.max_participants,
            Course.max_participants.label('course_max'),
            func.count(EventRegistration.id).label('active_count'),
        )
        .join(Course, Course.id == CourseInstance.course_id)
        .outerjoin(
            EventRegistration,
            db.and_(
                EventRegistration.instance_id == CourseInstance.id,
                EventRegistration.status.notin_(['cancelled']),
            ),
        )
        .filter(
            CourseInstance.course_id.in_(course_ids),
            CourseInstance.status.in_(('published', 'active')),
        )
        .group_by(CourseInstance.id, CourseInstance.max_participants, Course.max_participants)
        .all()
    )
    open_ids = set()
    for inst_id, inst_max, course_max, active_count in rows:
        cap = inst_max if inst_max is not None else course_max
        if cap is None or active_count < cap:
            open_ids.add(inst_id)
    return open_ids


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
             and (i.start_date is None or ensure_utc(i.start_date) >= now)],
            key=lambda i: ensure_utc(i.start_date) or datetime.max.replace(tzinfo=timezone.utc),
        )
        for c in courses
    }

    # Плоский список найближчих instances для секції "Графік"
    upcoming_instances = sorted(
        [i for c in courses for i in upcoming_by_course[c.id]],
        key=lambda i: ensure_utc(i.start_date) or datetime.max.replace(tzinfo=timezone.utc),
    )

    open_ids = _open_instance_ids([c.id for c in courses])

    return render_template(
        'courses/list.html',
        active_nav='courses',
        courses=courses,
        upcoming_by_course=upcoming_by_course,
        upcoming_instances=upcoming_instances,
        open_instance_ids=open_ids,
    )


@courses_bp.route('/<slug>')
def course_by_slug(slug):
    """Детальна сторінка курсу: контент Course + список проведень."""
    if slug in LEGACY_REDIRECTS:
        return redirect(
            url_for('courses.course_by_slug', slug=LEGACY_REDIRECTS[slug]),
            code=301,
        )

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
         and (i.start_date is None or ensure_utc(i.start_date) >= now)],
        key=lambda i: ensure_utc(i.start_date) or datetime.max.replace(tzinfo=timezone.utc),
    )
    # Минулі проведення: completed (фінальний стан) або published/active з датою
    # в минулому. Виключаємо draft (внутрішня кухня) та cancelled (скасовані).
    past_instances = sorted(
        [i for i in course.instances
         if i.status == 'completed'
         or (i.status in ('published', 'active')
             and i.start_date and ensure_utc(i.start_date) < now)],
        key=lambda i: ensure_utc(i.start_date) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    open_ids = _open_instance_ids([course.id])

    return render_template(
        'courses/detail.html',
        active_nav='courses',
        course=course,
        upcoming_instances=upcoming_instances,
        past_instances=past_instances,
        open_instance_ids=open_ids,
    )


def _validate_request_email(raw):
    """Повертає нормалізований email або None якщо невалідний / задовгий."""
    if not raw or len(raw) > _REQUEST_EMAIL_MAX:
        return None
    try:
        result = validate_email(raw, check_deliverability=False)
    except EmailNotValidError:
        return None
    return result.normalized


@courses_bp.route('/<slug>/request', methods=['POST'])
@limiter.limit('5 per hour; 20 per day', methods=['POST'])
def course_request(slug):
    """Клієнтський запит на проведення курсу (коли немає запланованих дат)."""
    course = Course.query.filter_by(slug=slug, is_active=True).first()
    if not course:
        abort(404)

    # Honeypot: приховане поле "website"; якщо заповнено -- спам-бот.
    if (request.form.get('website') or '').strip():
        current_app.logger.info('course_request honeypot triggered slug=%s', slug)
        # Мовчки приймаємо (відповідаємо redirect'ом як при успіху), щоб не
        # давати боту сигнал про detection.
        return redirect(url_for('courses.course_by_slug', slug=slug) + '#request-sent')

    email_raw = (request.form.get('email') or '').strip()
    phone_raw = (request.form.get('phone') or '').strip()
    message_raw = (request.form.get('message') or '').strip()

    email = _validate_request_email(email_raw)
    if not email:
        flash('Вкажіть валідний email', 'error')
        return redirect(url_for('courses.course_by_slug', slug=slug) + '#request')

    if len(phone_raw) > _REQUEST_PHONE_MAX:
        flash('Номер телефону задовгий', 'error')
        return redirect(url_for('courses.course_by_slug', slug=slug) + '#request')

    if len(message_raw) > _REQUEST_MESSAGE_MAX:
        flash('Повідомлення задовге (макс. 2000 символів)', 'error')
        return redirect(url_for('courses.course_by_slug', slug=slug) + '#request')

    user_id = current_user.id if current_user.is_authenticated else None

    req = CourseRequest(
        course_id=course.id,
        user_id=user_id,
        email=email,
        phone=phone_raw or None,
        message=message_raw or None,
        status='pending',
    )
    db.session.add(req)
    try:
        db.session.commit()
        flash('Дякуємо! Ми повідомимо вас коли буде запланована дата.', 'success')
        # Best-effort нотифікація адміну. Падіння SMTP не впливає на UX
        # користувача -- запит вже збережено.
        try:
            from app.services.email_service import EmailService
            EmailService.send_course_request_notification(req)
        except Exception:
            current_app.logger.exception(
                'Failed to send admin notification for CourseRequest #%s', req.id,
            )
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'Failed to save CourseRequest for course_id=%s email=%s', course.id, email,
        )
        flash('Помилка при надсиланні запиту. Спробуйте ще раз.', 'error')

    return redirect(url_for('courses.course_by_slug', slug=slug) + '#request-sent')


