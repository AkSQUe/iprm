"""Partner API v1 — учасники, реєстрації та ліди.

Партнер (MM Medic) будує ЄДИНУ базу клієнтів: менеджери мають бачити людей,
які прийшли через навчання, і працювати з ними в одній адмінці. Доти назовні
віддавалися лише заходи, тож картка учасника не існувала для партнера взагалі,
а зіставляти було нічого.

Три рішення, які визначають форму цих ендпоінтів.

**Курсор, а не повна вибірка.** Кожен приймає `updated_since` і віддає
відсортоване за `updated_at`. Без цього партнер щопівгодини тягнув би всю базу
через сторінки по сотні -- і однаково не дізнався б, що саме змінилось.

**Телефон -- головний ключ зіставлення.** Віддається канонічний `phone_e164`,
а не сирий рядок: близько третини акаунтів мають технічні email-адреси
(`@noemail.invalid`, `@xlsx.temp`), тож зшивати за поштою неможливо. Порожній
`phone_e164` означає «номер не розпізнаний» -- партнер має віднести таку
картку в чергу ручного розбору, а не вигадувати збіг.

**Ліди одним потоком.** `b2b_requests` і `course_requests` -- різні таблиці,
але для менеджера це один список «хтось залишив контакти». Розрізняє поле
`kind`; змішувати їх на боці партнера означало б два майже однакові
конвеєри.
"""
from flask import jsonify, make_response, request

from app.api.v1 import api_v1_bp
from app.api.v1.auth import require_api_key
from app.api.v1.serializers import API_VERSION
from app.extensions import csrf, db, limiter
from app.models.b2b_request import B2BRequest
from app.models.course_request import CourseRequest
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.user import User

MAX_PER_PAGE = 200
DEFAULT_PER_PAGE = 100

# Персональні дані не кешуються ні браузером, ні проксі: на відміну від
# каталогу заходів, тут кожна відповідь -- про конкретних людей.
_NO_STORE = 'no-store'


def _parse_updated_since():
    """(datetime|None, error|None) -- курсор інкрементальної вибірки."""
    raw = (request.args.get('updated_since') or '').strip()
    if not raw:
        return None, None
    from datetime import datetime, timezone
    # '+' у query-рядку декодується як пробіл, тож незакодований
    # `2026-08-11T00:00:00+00:00` доходить сюди як `...00:00 00:00`. Вимагати
    # від партнера ручного кодування -- це помилка, на яку він наступатиме
    # щоразу; дешевше прийняти обидві форми.
    raw = raw.replace(' ', '+')
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None, f'invalid updated_since: {raw!r}; expected ISO-8601'
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value, None


def _parse_pagination():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        return None, None, 'page/per_page must be integers'
    if page < 1:
        return None, None, 'page must be >= 1'
    if per_page < 1 or per_page > MAX_PER_PAGE:
        return None, None, f'per_page must be in [1, {MAX_PER_PAGE}]'
    return page, per_page, None


def _error(message, status=400):
    return jsonify({'error': message, 'api_version': API_VERSION}), status


def _envelope(pagination, items):
    return {
        'api_version': API_VERSION,
        'items': items,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
    }


def _private(response):
    response.headers['Cache-Control'] = _NO_STORE
    response.headers['Vary'] = 'X-API-Key'
    return response


def _iso(value):
    return value.isoformat() if value else None


def _listing(query, order_column, tiebreak_column=None):
    """Спільна обгортка: курсор, пагінація, стабільний порядок.

    Сортування завжди за `updated_at`, а не за id: партнер іде саме за
    курсором змін, і будь-який інший порядок робив би `updated_since`
    марним -- сторінка 2 могла б містити старіші зміни за сторінку 1.

    `tiebreak_column` -- друга колонка сортування. До 2026-08-14 цей коментар
    стверджував, що тайбрейкер є, а в `order_by` стояла ОДНА колонка. Різниця
    не теоретична: масовий імпорт ставить сотням рядків однаковий
    `updated_at`, PostgreSQL для рівних ключів порядок не гарантує, і рядки
    "плавають" між сторінками -- партнер бачить одні двічі, а інших не бачить
    зовсім, причому мовчки.
    """
    updated_since, err = _parse_updated_since()
    if err:
        return None, _error(err)
    page, per_page, err = _parse_pagination()
    if err:
        return None, _error(err)

    if updated_since is not None:
        query = query.filter(order_column >= updated_since)

    ordering = [order_column.asc()]
    if tiebreak_column is not None:
        ordering.append(tiebreak_column.asc())
    query = query.order_by(*ordering)
    return query.paginate(page=page, per_page=per_page, error_out=False), None


def _unsubscribe_url(user):
    """Посилання відписки цього учасника, якщо токен уже видано.

    Токен НЕ генерується тут: видача -- це запис у БД, а GET-ендпоінт бази
    не змінює. Порожнє значення означає «людина ще не отримувала листів із
    посиланням», і партнеру нічого показувати.
    """
    if not user.unsubscribe_token:
        return None
    from app.models.site_settings import SiteSettings

    # Той самий `website_url`, з якого будує посилання email_service: два
    # джерела базового URL розійшлися б, і половина листів вела б у нікуди.
    base = (SiteSettings.get().website_url or '').rstrip('/')
    return f'{base}/unsubscribe/{user.unsubscribe_token}' if base else None


def _suppressed_emails(emails):
    """Адреси зі списку, на які ми більше не пишемо."""
    from app.models.email_suppression import EmailSuppression

    normalized = [EmailSuppression.normalize(e) for e in emails if e]
    if not normalized:
        return set()

    rows = (
        db.session.query(EmailSuppression.email)
        .filter(EmailSuppression.email.in_(normalized))
        .all()
    )
    return {row[0] for row in rows}


def _deliverable(email, suppressed):
    if not email:
        return None
    from app.models.email_suppression import EmailSuppression

    return EmailSuppression.normalize(email) not in suppressed


@api_v1_bp.route('/participants', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('60 per minute')
def list_participants():
    """Учасники навчання: контакти + професійний профіль.

    Query: page, per_page (<=200), updated_since (ISO-8601).
    """
    query = (
        db.session.query(User, MedicalProfile)
        .outerjoin(MedicalProfile, MedicalProfile.user_id == User.id)
    )
    pagination, error = _listing(query, User.updated_at, User.id)
    if error:
        return error

    # Один запит на сторінку замість запиту на кожного учасника: сторінка --
    # це до 200 людей, і перевірка адреси поштучно перетворила б відповідь на
    # 200 SELECT-ів.
    suppressed = _suppressed_emails([user.email for user, _ in pagination.items])

    items = []
    for user, profile in pagination.items:
        items.append({
            'id': user.id,
            'email': user.email,
            'email_confirmed': bool(user.email_confirmed),
            'first_name': user.first_name,
            'last_name': user.last_name,
            'middle_name': profile.middle_name if profile else None,
            # Канонічна форма для зіставлення; None = не розпізнано.
            'phone_e164': profile.phone_e164 if profile else None,
            'phone_raw': profile.phone if profile else None,
            'participant_type': profile.participant_type if profile else None,
            'specializations': (profile.specializations or []) if profile else [],
            'workplace': profile.workplace if profile else None,
            'position': profile.position if profile else None,
            # Звідки взявся профіль: 'partner' означає, що людина прийшла з
            # MM Medic через prefill -- партнер не має вважати її своїм
            # «новим» лідом удруге.
            'source': profile.source if profile else None,
            'is_active': bool(user.is_active),
            # Згода на листи. Без цього поля партнер не знає, кому в нас
            # заборонено писати, і його розсилка обходить нашу відписку --
            # для людини це один відправник, і претензія буде до обох.
            'email_opt_out': bool(user.email_opt_out),
            # Посилання, яким людина відписалась у НАС. Партнер показує його
            # у своїх листах про навчання, тож відписка лишається одна.
            'unsubscribe_url': _unsubscribe_url(user),
            # Чи дійде лист узагалі: адреса могла потрапити в suppression
            # після відбиття. `None` -- ми не перевіряли.
            'email_deliverable': _deliverable(user.email, suppressed),
            'last_login_at': _iso(user.last_login_at),
            'created_at': _iso(user.created_at),
            'updated_at': _iso(user.updated_at),
        })

    return _private(make_response(jsonify(_envelope(pagination, items))))


@api_v1_bp.route('/registrations', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('60 per minute')
def list_registrations():
    """Реєстрації на проведення: статус, оплата, присутність.

    Query: page, per_page (<=200), updated_since (ISO-8601).
    """
    from app.models.course_instance import CourseInstance

    # User приєднується обов'язково: ім'я й пошта живуть на картці, а не в
    # реєстрації -- без них партнер отримував рядок без жодної ознаки, КОГО
    # він показує, і список у його адмінці був із порожньою колонкою учасника.
    query = (
        db.session.query(EventRegistration, CourseInstance, User, MedicalProfile)
        .join(CourseInstance, CourseInstance.id == EventRegistration.instance_id)
        .outerjoin(User, User.id == EventRegistration.user_id)
        .outerjoin(MedicalProfile, MedicalProfile.user_id == EventRegistration.user_id)
    )
    pagination, error = _listing(query, EventRegistration.updated_at,
                                 EventRegistration.id)
    if error:
        return error

    items = []
    for reg, instance, user, profile in pagination.items:
        items.append({
            'id': reg.id,
            'user_id': reg.user_id,
            'first_name': user.first_name if user else None,
            'last_name': user.last_name if user else None,
            'middle_name': profile.middle_name if profile else None,
            'email': user.email if user else None,
            # Канонічний телефон із профілю -- ключ зіставлення; `phone` нижче
            # це те, що людина вписала в анкету саме на цю реєстрацію.
            'phone_e164': profile.phone_e164 if profile else None,
            'instance_id': reg.instance_id,
            'course_slug': instance.course.slug if instance.course else None,
            'course_title': instance.course.title if instance.course else None,
            'start_date': _iso(instance.start_date),
            'status': reg.status,
            'payment_status': reg.payment_status,
            'payment_method': reg.payment_method,
            'payment_amount': (
                float(reg.payment_amount) if reg.payment_amount is not None else None
            ),
            'paid_at': _iso(reg.paid_at),
            'attended': bool(reg.attended),
            'cpd_points_awarded': reg.cpd_points_awarded,
            # Знімок анкети на момент реєстрації: людина могла відтоді
            # змінити місце роботи, а партнеру потрібен саме той стан.
            'phone': reg.phone,
            'specialty': reg.specialty,
            'workplace': reg.workplace,
            'referral_code': reg.referral_code,
            'created_at': _iso(reg.created_at),
            'updated_at': _iso(reg.updated_at),
        })

    return _private(make_response(jsonify(_envelope(pagination, items))))


@api_v1_bp.route('/leads', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('60 per minute')
def list_leads():
    """Заявки, що не є реєстрацією: B2B і запити на курс.

    Два джерела в одному потоці, розрізняються полем `kind`. Пагінація тут
    застосовується ПІСЛЯ обʼєднання, тож повертається загальна кількість, а
    не сума двох незалежних вибірок.
    """
    updated_since, err = _parse_updated_since()
    if err:
        return _error(err)
    page, per_page, err = _parse_pagination()
    if err:
        return _error(err)

    b2b = B2BRequest.query
    course = CourseRequest.query
    if updated_since is not None:
        b2b = b2b.filter(B2BRequest.updated_at >= updated_since)
        course = course.filter(CourseRequest.updated_at >= updated_since)

    rows = []
    for item in b2b.all():
        rows.append({
            'kind': 'b2b',
            'id': f'b2b-{item.id}',
            'user_id': None,
            'first_name': item.first_name,
            'last_name': item.last_name,
            'email': item.email,
            'phone': item.phone,
            'team_size': item.team_size,
            'course_slug': None,
            'message': None,
            'status': item.status,
            'admin_notes': item.admin_notes,
            'created_at': _iso(item.created_at),
            'updated_at': _iso(item.updated_at),
        })
    for item in course.all():
        rows.append({
            'kind': 'course_request',
            'id': f'course-{item.id}',
            # Заповнений лише коли людина була залогінена -- саме тоді
            # партнер може одразу привʼязати заявку до наявної картки.
            'user_id': item.user_id,
            'first_name': None,
            'last_name': None,
            'email': item.email,
            'phone': item.phone,
            'team_size': None,
            'course_slug': item.course.slug if item.course else None,
            'message': item.message,
            'status': item.status,
            'admin_notes': item.admin_notes,
            'created_at': _iso(item.created_at),
            'updated_at': _iso(item.updated_at),
        })

    rows.sort(key=lambda r: (r['updated_at'] or '', r['id']))
    total = len(rows)
    start = (page - 1) * per_page
    window = rows[start:start + per_page]

    body = {
        'api_version': API_VERSION,
        'items': window,
        'page': page,
        'per_page': per_page,
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page else 0,
    }
    return _private(make_response(jsonify(body)))


@api_v1_bp.route('/participants/<int:user_id>/opt-out', methods=['POST'])
@csrf.exempt
@require_api_key
@limiter.limit('120 per minute')
def participant_opt_out(user_id):
    """Партнер повідомляє, що людина відписалась У НЬОГО.

    Згоди двох систем мають сходитись. Людина натискає «відписатись» у листі
    MM Medic про наші ж курси -- для неї це ОДИН відправник, і те, що частину
    листів шле партнер, а частину ми, її не цікавить. Без цього ендпоінта ми
    продовжували б писати, і винними виглядали б обидва.

    Ефект той самий, що й у нашої сторінки `/unsubscribe/<token>`: прапорець
    `email_opt_out`. Другого поняття «відписка» не заводимо -- воно розійшлося
    б із першим на першому ж листі.

    Ідемпотентний: повторний виклик повертає 200 і нічого не змінює. Партнер
    ретраїть при мережевих збоях, і 409 на другій спробі означав би, що він
    ретраїтиме вічно.
    """
    user = db.session.get(User, user_id)
    if user is None:
        return _error('participant not found', 404)

    payload = request.get_json(silent=True) or {}
    reason = str(payload.get('reason') or '')[:200]
    resubscribe = payload.get('action') == 'resubscribe'

    changed = user.email_opt_out == resubscribe
    user.email_opt_out = not resubscribe
    if changed:
        db.session.commit()

    return _private(make_response(jsonify({
        'api_version': API_VERSION,
        'id': user.id,
        'email_opt_out': bool(user.email_opt_out),
        'changed': bool(changed),
        'reason': reason or None,
    })))


@api_v1_bp.route('/online-enrollments', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('60 per minute')
def list_online_enrollments():
    """Покупки онлайн-курсів: хто, що, за скільки і чи оплачено.

    Потрібні партнеру, щоб показувати такі покупки в одному списку
    реєстрацій зі своїми: без них у нього видно каталог курсів, але не
    видно жодної людини, яка їх купила.

    Токен доступу і посилання на навчання НЕ віддаються ніколи -- вони не
    потрібні для обліку, а віддати їх означало б винести ключ від курсу за
    межі системи, яка ним керує.

    Query: page, per_page (<=200), updated_since (ISO-8601).
    """
    from app.models.online_course import OnlineCourse
    from app.models.online_enrollment import OnlineEnrollment

    query = (
        db.session.query(OnlineEnrollment, OnlineCourse, User, MedicalProfile)
        .join(OnlineCourse, OnlineCourse.id == OnlineEnrollment.online_course_id)
        .outerjoin(User, User.id == OnlineEnrollment.user_id)
        .outerjoin(MedicalProfile, MedicalProfile.user_id == OnlineEnrollment.user_id)
    )
    pagination, error = _listing(query, OnlineEnrollment.updated_at,
                                 OnlineEnrollment.id)
    if error:
        return error

    items = []
    for enrollment, course, user, profile in pagination.items:
        items.append({
            'id': enrollment.id,
            'order_id': enrollment.order_id,
            'user_id': enrollment.user_id,
            'first_name': user.first_name if user else None,
            'last_name': user.last_name if user else None,
            'middle_name': profile.middle_name if profile else None,
            'email': user.email if user else None,
            # Той самий ключ зіставлення, що й у реєстраціях на заходи.
            'phone_e164': profile.phone_e164 if profile else None,
            'course_id': course.id,
            'course_slug': course.slug,
            'course_title': course.effective_title,
            'status': enrollment.status,
            'payment_status': enrollment.payment_status,
            'payment_method': enrollment.payment_method,
            'payment_amount': (
                float(enrollment.payment_amount)
                if enrollment.payment_amount is not None else None
            ),
            'currency': course.currency,
            'paid_at': _iso(enrollment.paid_at),
            # Чи людина вже реально почала навчання -- єдина ознака
            # «присутності», яка тут взагалі можлива.
            'access_opened_at': _iso(enrollment.access_last_opened_at),
            'created_at': _iso(enrollment.created_at),
            'updated_at': _iso(enrollment.updated_at),
        })

    return _private(make_response(jsonify(_envelope(pagination, items))))
