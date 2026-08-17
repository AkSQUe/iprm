from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

from email_validator import EmailNotValidError, validate_email
from flask import (
    Response, abort, current_app, flash, jsonify, redirect, render_template,
    request, url_for,
)
from flask_babel import gettext as _
from flask_login import current_user
from sqlalchemy.orm import joinedload, selectinload

from app.courses import courses_bp
from app.extensions import db, limiter
from app.models.b2b_request import B2BRequest
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_request import CourseRequest
from app.services import quiz_service
from app.services.recaptcha import verify_request as verify_recaptcha
from app.utils import ensure_utc

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
    # Злиття NRP онлайн+офлайн в один курс (nrp_merge_20260708).
    'nrp-neuro-relax-protocol-offline': 'nrp-neuro-relax-protocol',
}


# Хелпери місткості винесено у спільний сервіс (course_listing) -- реюз із
# Головною. Аліаси зберігають наявні внутрішні виклики без змін.
from app.services.course_listing import (  # noqa: E402
    capacity_map as _capacity_map,
    open_from_capacity as _open_from_capacity,
)


_ATTENDANCE_MODE = {
    'online': 'https://schema.org/OnlineEventAttendanceMode',
    'offline': 'https://schema.org/OfflineEventAttendanceMode',
    'hybrid': 'https://schema.org/MixedEventAttendanceMode',
}


def _event_jsonld(inst, is_open):
    """schema.org/EducationEvent-вузол для одного проведення (для SEO)."""
    course = inst.course
    course_url = url_for('courses.course_by_slug', slug=course.slug, _external=True)
    node = {
        '@context': 'https://schema.org',
        '@type': 'EducationEvent',
        'name': course.title,
        'startDate': ensure_utc(inst.start_date).isoformat(),
        'eventAttendanceMode': _ATTENDANCE_MODE.get(
            inst.event_format, _ATTENDANCE_MODE['offline'],
        ),
        'eventStatus': 'https://schema.org/EventScheduled',
        'organizer': {
            '@type': 'Organization',
            'name': 'ІПРМ',
            'url': url_for('main.index', _external=True),
        },
        'url': course_url,
    }
    if inst.end_date:
        node['endDate'] = ensure_utc(inst.end_date).isoformat()

    description = course.short_description or course.subtitle
    if description:
        node['description'] = description

    if course.card_src:
        node['image'] = urljoin(request.url_root, course.card_src)

    place = {
        '@type': 'Place',
        'name': inst.location or 'Україна',
        'address': inst.location or 'Україна',
    }
    virtual = {'@type': 'VirtualLocation', 'url': inst.online_link or course_url}
    if inst.event_format == 'online':
        node['location'] = virtual
    elif inst.event_format == 'hybrid':
        node['location'] = [virtual, place]
    else:
        node['location'] = place

    trainer = inst.effective_trainer
    if trainer:
        node['performer'] = {'@type': 'Person', 'name': trainer.full_name}

    price = inst.effective_price
    if price and price > 0:
        offer = {
            '@type': 'Offer',
            'price': str(int(price)),
            'priceCurrency': 'UAH',
            'availability': (
                'https://schema.org/InStock' if is_open
                else 'https://schema.org/SoldOut'
            ),
            'url': url_for('registration.register_instance', instance_id=inst.id, _external=True),
        }
        if inst.created_at:
            offer['validFrom'] = ensure_utc(inst.created_at).isoformat()
        node['offers'] = offer

    return node


def _serialize_event(inst, capacity):
    """Серіалізує CourseInstance у dict для календаря (inline + JSON-feed).

    `capacity` -- мапа {instance_id: seats_left} з _capacity_map; для проведень
    поза нею (напр. completed) вважаємо реєстрацію закритою.
    """
    seats_left = capacity.get(inst.id)
    is_open = inst.id in capacity and (seats_left is None or seats_left > 0)
    return {
        'id': inst.id,
        'date': inst.start_date.strftime('%Y-%m-%d'),
        'end': inst.end_date.strftime('%Y-%m-%d') if inst.end_date else None,
        'title': inst.course.t('title'),
        'slug': inst.course.slug,
        'format': inst.event_format,
        'format_label': inst.format_label,
        'event_type': inst.course.event_type,
        'event_type_label': inst.course.event_type_label,
        'tags': inst.course.t('tags') or [],
        'trainer': inst.effective_trainer.t('full_name') if inst.effective_trainer else None,
        'cpd': inst.effective_cpd_points,
        'price': (
            int(inst.effective_price)
            if inst.effective_price and inst.effective_price > 0
            else None
        ),
        'location': inst.location or '',
        'seats_left': seats_left,
        'is_open': is_open,
        'past': inst.status == 'completed',
        'register_url': url_for('registration.register_instance', instance_id=inst.id),
        'course_url': url_for('courses.course_by_slug', slug=inst.course.slug),
        'ics_url': url_for('courses.event_ics', instance_id=inst.id),
    }


def _ics_escape(text):
    """Екранування TEXT-значень за RFC 5545 (\\ ; , та переноси рядків)."""
    return (
        (text or '')
        .replace('\\', '\\\\')
        .replace(';', '\\;')
        .replace(',', '\\,')
        .replace('\r\n', '\\n')
        .replace('\n', '\\n')
    )


@courses_bp.route('/')
def course_list():
    """Каталог: всі активні курси (навіть без запланованих проведень)."""
    from app.services import course_listing
    courses, upcoming_by_course, capacity, open_ids = (
        course_listing.gather_active_courses()
    )
    # Дефолтне сортування каталогу -- за датою найближчого проведення
    # (закріплені лишаються зверху). JS-режим "За замовчуванням" відновлює
    # саме цей порядок, бо спирається на початковий індекс картки в DOM.
    courses = course_listing.order_by_nearest(courses, upcoming_by_course)

    # Плоский список найближчих instances для секції "Графік".
    # `upcoming_instances` -- топ-5 для view-режиму "Список".
    # `upcoming_instances_all` -- усі майбутні для view-режиму "Календар".
    upcoming_instances_all = sorted(
        [i for c in courses for i in upcoming_by_course[c.id]],
        key=lambda i: ensure_utc(i.start_date) or datetime.max.replace(tzinfo=timezone.utc),
    )
    upcoming_instances = upcoming_instances_all[:5]

    # Унікальні теги каталогу для бігучого рядка чіпсів (за спаданням частоти,
    # щоб найпоширеніші спеціальності були першими).
    tag_counts = {}
    for c in courses:
        for tag in (c.tags or []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    all_tags = sorted(tag_counts, key=lambda t: (-tag_counts[t], t))

    # JSON-серіалізована стрічка майбутніх подій для inline-старту календаря.
    # `date` (YYYY-MM-DD) -- all-day start у FullCalendar: date-only рядок не
    # конвертується по часових поясах -> жодного зсуву дати. Архів минулих
    # заходів довантажується ледаче через /courses/calendar.json.
    schedule_events = [
        _serialize_event(inst, capacity)
        for inst in upcoming_instances_all if inst.start_date
    ]

    # schema.org/EducationEvent для кожного проведення -> rich results у Google.
    events_jsonld = [
        _event_jsonld(inst, inst.id in open_ids)
        for inst in upcoming_instances_all if inst.start_date
    ]

    return render_template(
        'courses/list.html',
        active_nav='courses',
        courses=courses,
        upcoming_by_course=upcoming_by_course,
        upcoming_instances=upcoming_instances,
        schedule_events=schedule_events,
        events_jsonld=events_jsonld,
        open_instance_ids=open_ids,
        seats_left_map=capacity,
        all_tags=all_tags,
    )


def _parse_feed_date(raw):
    """Парсить YYYY-MM-DD (FullCalendar шле ISO; беремо лише дату) -> aware UTC."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@courses_bp.route('/calendar.json')
def calendar_json():
    """JSON-feed подій для FullCalendar у заданому діапазоні дат.

    Включає completed-проведення -> перегляд архіву минулих заходів. Календар
    кешує inline-майбутні події й довантажує цей feed лише для поточного/минулих
    місяців (див. page-courses-schedule.js).
    """
    start_dt = _parse_feed_date(request.args.get('start'))
    end_dt = _parse_feed_date(request.args.get('end'))

    query = (
        CourseInstance.query
        .options(
            joinedload(CourseInstance.course),
            joinedload(CourseInstance.trainer),
        )
        .join(Course, Course.id == CourseInstance.course_id)
        .filter(
            Course.is_active.is_(True),
            CourseInstance.status.in_(('published', 'active', 'completed')),
            CourseInstance.start_date.isnot(None),
        )
    )
    if start_dt is not None:
        query = query.filter(CourseInstance.start_date >= start_dt)
    if end_dt is not None:
        query = query.filter(CourseInstance.start_date < end_dt)

    # Стеля на захист від запитів без діапазону / надмірних вибірок.
    instances = query.order_by(CourseInstance.start_date).limit(500).all()
    capacity = _capacity_map(list({i.course_id for i in instances}))
    events = [_serialize_event(inst, capacity) for inst in instances]

    response = jsonify({'events': events})
    response.headers['Cache-Control'] = 'public, max-age=300'
    return response


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
        selectinload(Course.instances).selectinload(CourseInstance.tariffs),
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

    capacity = _capacity_map([course.id])
    open_ids = _open_from_capacity(capacity)

    # Реферальне посилання на цей курс (лише для залогінених, коли програму
    # увімкнено). Код генерується лениво при першому відкритті сторінки.
    from app.services import referral_service
    referral_link = None
    if current_user.is_authenticated:
        from app.models.site_settings import SiteSettings
        if SiteSettings.get().referral_enabled:
            had_code = bool(current_user.referral_code)
            referral_link = referral_service.user_referral_link(
                current_user,
                target_url=url_for('courses.course_by_slug', slug=course.slug),
            )
            if not had_code:  # код щойно згенеровано -> зберегти
                db.session.commit()
    # Банер довіри: якщо прибули за реф-посиланням -- показати, хто рекомендує.
    referral_inviter = referral_service.current_inviter_name(
        request, current_user if current_user.is_authenticated else None,
    )

    # Опубліковані відгуки, привʼязані до цього курсу.
    from app.models.review import Review
    course_reviews = Review.alive().filter_by(
        course_id=course.id, is_published=True,
    ).order_by(Review.sort_order, Review.created_at.desc()).limit(6).all()

    # Крос-сел "Наступний крок": спільний сервіс із екранами після оплати.
    from app.services.course_recommend import recommend_context
    recommend = recommend_context(
        base_course=course,
        user=current_user if current_user.is_authenticated else None,
    )

    return render_template(
        'courses/detail.html',
        active_nav='courses',
        course=course,
        upcoming_instances=upcoming_instances,
        past_instances=past_instances,
        open_instance_ids=open_ids,
        seats_left_map=capacity,
        referral_link=referral_link,
        referral_inviter=referral_inviter,
        course_reviews=course_reviews,
        certificate_quiz=quiz_service.public_quiz_for_course(course),
        **recommend,
    )


@courses_bp.route('/event/<int:instance_id>.ics')
def event_ics(instance_id):
    """Віддає .ics (iCalendar) для одного проведення -- кнопка 'Додати в календар'.

    Подія -- all-day (VALUE=DATE), узгоджено з all-day рендером у календарі:
    уникаємо неоднозначностей часових поясів. DTEND ексклюзивний.
    """
    inst = (
        CourseInstance.query
        .options(joinedload(CourseInstance.course))
        .get(instance_id)
    )
    if (
        inst is None
        or inst.course is None
        or not inst.course.is_active
        or inst.status not in ('published', 'active')
        or inst.start_date is None
    ):
        abort(404)

    start = ensure_utc(inst.start_date)
    end = ensure_utc(inst.end_date) if inst.end_date else start
    # DTEND для all-day -- ексклюзивний: дата завершення + 1 день.
    dtend_date = end.date() + timedelta(days=1)

    course_url = url_for('courses.course_by_slug', slug=inst.course.slug, _external=True)
    location = 'Онлайн' if inst.event_format == 'online' else (inst.location or '')
    description = inst.course.short_description or inst.course.subtitle or ''
    description = (description + '\n' + course_url).strip()

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//IPRM//Courses//UK',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        'UID:course-instance-%d@iprm.com.ua' % inst.id,
        'DTSTAMP:' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
        'DTSTART;VALUE=DATE:' + start.strftime('%Y%m%d'),
        'DTEND;VALUE=DATE:' + dtend_date.strftime('%Y%m%d'),
        'SUMMARY:' + _ics_escape(inst.course.title),
        'DESCRIPTION:' + _ics_escape(description),
        'URL:' + course_url,
        'END:VEVENT',
        'END:VCALENDAR',
    ]
    if location:
        lines.insert(-2, 'LOCATION:' + _ics_escape(location))
    body = '\r\n'.join(lines) + '\r\n'

    return Response(
        body,
        mimetype='text/calendar',
        headers={
            'Content-Disposition': 'attachment; filename="iprm-event-%d.ics"' % inst.id,
            'Cache-Control': 'public, max-age=600',
        },
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


@courses_bp.route('/b2b-request', methods=['POST'])
@limiter.limit('5 per hour; 20 per day', methods=['POST'])
def b2b_request():
    """Лід-форма корпоративного навчання (блок "Для команд і клінік")."""
    back = url_for('courses.course_list') + '#b2b'

    # Honeypot: приховане поле "website"; якщо заповнено -- спам-бот.
    if (request.form.get('website') or '').strip():
        current_app.logger.info('b2b_request honeypot triggered')
        return redirect(back + '-sent')

    if not verify_recaptcha(action='b2b_request'):
        flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
        return redirect(back)

    first_name = (request.form.get('first_name') or '').strip()
    last_name = (request.form.get('last_name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    team_size = (request.form.get('team_size') or '').strip()
    email = _validate_request_email((request.form.get('email') or '').strip())

    if not first_name or not last_name or len(first_name) > 120 or len(last_name) > 120:
        flash(_('Вкажіть ім\'я та прізвище'), 'error')
        return redirect(back)
    if not phone or len(phone) > _REQUEST_PHONE_MAX:
        flash(_('Вкажіть коректний номер телефону'), 'error')
        return redirect(back)
    if not email:
        flash(_('Вкажіть валідний email'), 'error')
        return redirect(back)
    if team_size not in {code for code, _ in B2BRequest.TEAM_SIZES}:
        flash(_('Оберіть кількість фахівців'), 'error')
        return redirect(back)

    req = B2BRequest(
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email,
        team_size=team_size,
    )
    db.session.add(req)
    try:
        db.session.commit()
        flash(_('Дякуємо! Ми зв\'яжемось з вами щодо корпоративних умов.'), 'success')
        # Best-effort admin-нотифікація: заявку вже збережено, збій SMTP
        # не має впливати на UX.
        from app.services.email_service import EmailService
        try:
            EmailService.send_b2b_request_notification(req)
        except Exception:
            current_app.logger.exception(
                'Failed to send admin notification for B2BRequest #%s', req.id,
            )
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to save B2BRequest email=%s', email)
        flash(_('Помилка при надсиланні заявки. Спробуйте ще раз.'), 'error')

    return redirect(back + '-sent')


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

    if not verify_recaptcha(action='course_request'):
        flash(_('Перевірка reCAPTCHA не пройдена. Спробуйте ще раз.'), 'error')
        return redirect(url_for('courses.course_by_slug', slug=slug) + '#request')

    email_raw = (request.form.get('email') or '').strip()
    phone_raw = (request.form.get('phone') or '').strip()
    message_raw = (request.form.get('message') or '').strip()

    email = _validate_request_email(email_raw)
    if not email:
        flash(_('Вкажіть валідний email'), 'error')
        return redirect(url_for('courses.course_by_slug', slug=slug) + '#request')

    if len(phone_raw) > _REQUEST_PHONE_MAX:
        flash(_('Номер телефону задовгий'), 'error')
        return redirect(url_for('courses.course_by_slug', slug=slug) + '#request')

    if len(message_raw) > _REQUEST_MESSAGE_MAX:
        flash(_('Повідомлення задовге (макс. 2000 символів)'), 'error')
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
        flash(_('Дякуємо! Ми повідомимо вас коли буде запланована дата.'), 'success')
        # Best-effort нотифікації (admin + клієнтське ack). Падіння SMTP не
        # впливає на UX користувача -- запит уже збережено. Кожна гілка
        # обгорнута власним try, щоб збій однієї не блокував іншу.
        from app.services.email_service import EmailService
        try:
            EmailService.send_course_request_notification(req)
        except Exception:
            current_app.logger.exception(
                'Failed to send admin notification for CourseRequest #%s', req.id,
            )
        try:
            EmailService.send_course_request_received(req)
        except Exception:
            current_app.logger.exception(
                'Failed to send client ack for CourseRequest #%s', req.id,
            )
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'Failed to save CourseRequest for course_id=%s email=%s', course.id, email,
        )
        flash(_('Помилка при надсиланні запиту. Спробуйте ще раз.'), 'error')

    return redirect(url_for('courses.course_by_slug', slug=slug) + '#request-sent')


