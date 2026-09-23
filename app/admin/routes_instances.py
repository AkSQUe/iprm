"""Admin CRUD для CourseInstance (проведення)."""
import logging
from datetime import datetime, timedelta, timezone

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import current_user
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload, selectinload

from app.admin import _listing, admin_bp
from app.admin.routes_translations import apply_inline_translations
from app.admin._helpers import (
    populate_event_type_choices,
    populate_trainer_choices,
    try_commit,
)
from app.rbac import permission_required
from app.admin.forms import CourseInstanceForm
from app.extensions import db, limiter
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.services import course_service, event_types
from app.services.course_service import InvalidStatusTransition
from app.services.seating import occupied_clause, occupied_counts

audit_logger = logging.getLogger('audit')


def _wants_json():
    """Клієнт очікує JSON (AJAX) замість redirect (noscript fallback)."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.accept_mimetypes
    return accept.best_match(['application/json', 'text/html']) == 'application/json'


def _populate_choices(form, preselected_course_id=None, instance=None):
    courses = (
        Course.query.filter_by(is_active=True)
        .order_by(Course.title)
        .all()
    )
    form.course_id.choices = [(c.id, c.title) for c in courses]
    if preselected_course_id and not form.course_id.data:
        form.course_id.data = preselected_course_id

    # linked_ids -- див. docstring populate_trainer_choices: без нього
    # деактивований, але вже прив'язаний до проведення тренер випадає з
    # choices і зникає з форми на першому ж збереженні.
    populate_trainer_choices(
        form, linked_ids=[t.id for t in instance.trainers] if instance else None,
    )

    # Місто необов'язкове: адресу часто знають пізніше за дату, і розклад
    # показує «Місце уточнюється» замість того, щоб ховати захід.
    from app.models.city import City
    form.city_id.choices = [(0, '– Місце уточнюється –')] + [
        (city.id, city.name) for city in City.query.order_by(City.name).all()
    ]

    from app.services import specialties
    # Збережене в БД, а НЕ form.data: на POST form.data -- це щойно надіслані
    # значення, і "тримати обраний деактивований код" звелося б до "тримати
    # будь-що надіслане" -- pre_validate пропускав би навіть код, якого в
    # цього проведення ніколи не було. current мусить бути тим, що реально
    # записано зараз (як і в course_edit -- current=course.bpr_specialty_codes).
    instance_codes = instance.bpr_specialty_codes if instance else None
    form.bpr_specialty_codes.choices = specialties.choices(current=instance_codes)

    # Той самий доказ, що й у спеціальностей вище: чинний вид заходу беремо
    # зі збереженого проведення, а не з form.data.
    populate_event_type_choices(
        form, current=(instance.event_type if instance else None),
        empty_label=_inherited_type_label(instance, preselected_course_id),
    )

    form.difficulty_level.choices = (
        [(0, _inherited_level_label(
            _inherited_source(instance, preselected_course_id)))]
        + Course.DIFFICULTY_LEVELS
    )

    form.bpr_event_number.render_kw = {
        'placeholder': _inherited_event_number_hint(instance, preselected_course_id),
    }


_BARE_INHERITED = '– Як у курсу –'

# Підказка порожнього поля номера, коли курс іще не відомий (чисте /new).
_BARE_EVENT_NUMBER_HINT = '7 цифр'


def _inherited_event_number_hint(instance, preselected_course_id=None):
    """Плейсхолдер поля «Реєстраційний номер заходу БПР».

    Порожнє поле означає «візьметься номер курсу», і саме його адмін і має
    побачити: сертифікат піде під ним, а перевіряти це в картці курсу --
    зайвий перехід. Та сама логіка, що в підписів виду заходу й рівня.
    """
    course = _known_course(instance, preselected_course_id)
    number = (course.bpr_event_number or '').strip() if course else ''
    return f'{number} (з курсу)' if number else _BARE_EVENT_NUMBER_HINT


def _inherited_type_label(instance, preselected_course_id=None):
    """Підпис порожнього варіанта поля «Вид заходу».

    Голе «Як у курсу» не повідомляє нічого: щоб дізнатись, тренінг це чи
    фахова школа, довелось би відкрити картку курсу. Тому називаємо тип у
    дужках скрізь, де курс уже відомий -- і в правці наявної дати, і в
    створенні з картки курсу (?course_id=). На чистому /new курс обирають
    у тій самій формі, називати ще нічого.
    """
    course = _known_course(instance, preselected_course_id)
    if course is None or not course.event_type:
        return _BARE_INHERITED
    return f'– Як у курсу ({course.event_type_label}) –'


def _known_course(instance, preselected_course_id=None):
    """Курс, до якого належить (чи належатиме) проведення, якщо він відомий.

    Спільне для всіх успадкованих полів: у правці дати курс беремо з неї,
    у створенні з картки курсу -- з ?course_id=. На чистому /new курс
    обирають у тій самій формі, тож відомого курсу ще немає.
    """
    course = instance.course if instance is not None else None
    if course is None and preselected_course_id:
        course = db.session.get(Course, preselected_course_id)
    return course


def _inherited_source(instance, preselected_course_id=None):
    """Курс, із якого проведення бере незаповнені поля блоку Override.

    Порожнє поле там означає «як у курсу», тож форма мусить називати саме
    те, що буде взято, -- і в правці наявної дати, і в створенні з картки
    курсу (?course_id=). На чистому /new курс обирають у тій самій формі,
    тож називати ще нічого, і тут чесно повертається None.
    """
    if instance is not None and instance.course is not None:
        return instance.course
    if preselected_course_id:
        return db.session.get(Course, preselected_course_id)
    return None


def _inherited_level_label(course):
    """Підпис порожнього варіанта поля «Рівень складності».

    Голе «Як у курсу» приховує саме ту цифру, з якою адмін і збирається
    зіставити цю дату: щоб дізнатись, базовий курс чи поглиблений, довелось
    би відкрити його картку. Тому називаємо рівень у дужках скрізь, де курс
    уже відомий.
    """
    if course is None or not course.difficulty_level:
        return _BARE_INHERITED
    return f'– Як у курсу ({course.difficulty_label}) –'


def _issued_bpr(instance):
    """(к-сть, номери заходу) вже виданих сертифікатів цієї дати -- або None.

    Потрібне рівно для застереження біля поля номера: якщо сертифікати вже
    пішли під іншим номером, адмін мусить це побачити ДО правки, бо видані
    номери не переписуються.
    """
    from app.services import certificate_service

    count, numbers = certificate_service.issued_event_numbers(instance)
    return {'count': count, 'numbers': numbers} if count else None


_INSTANCES_PER_PAGE = 25


_QUICK_PRESETS = (
    'upcoming', 'next3', 'past', 'this_month', 'with_regs',
    'no_regs', 'free_seats', 'full', 'attention',
)


def _effective_type_clause(code):
    """Умова «ЕФЕКТИВНИЙ вид заходу дати == code».

    Не `CourseInstance.event_type == code`: перевизначення мають одиниці, і
    такий фільтр згубив би всі дати, що вид успадковують -- тобто майже всі.
    Екран виглядав би правдоподібно порожнім, а не зламаним.

    Успадкування перевіряємо через EXISTS (`.has`), а не join: `_instances_query`
    приєднує Course лише під пошук, і безумовний join довелося б там
    узгоджувати. Порожній рядок нарівні з NULL -- так само, як у
    CourseInstance.effective_event_type, де перевірка на істинність.
    """
    inherits = or_(
        CourseInstance.event_type.is_(None),
        CourseInstance.event_type == '',
    )
    return or_(
        CourseInstance.event_type == code,
        and_(inherits, CourseInstance.course.has(Course.event_type == code)),
    )


def _event_type_options():
    """Пари (код, назва) для фільтра -- з довідника, а не з констант.

    choice_arg звіряє значення саме з цим переліком, тож ?event_type=<сміття>
    тихо падає в порожній фільтр, а не в порожній екран (як у courses_list).
    """
    return [(code, row.name) for code, row in event_types.directory().items()]


def _instance_filters():
    """Фільтри списку проведень -- спільні для сторінки й експорту."""
    return {
        'q': _listing.text_arg('q'),
        'course_id': _listing.int_arg('course_id'),
        'status': _listing.choice_arg('status', dict(CourseInstance.STATUSES)),
        'event_type': _listing.choice_arg(
            'event_type', {code for code, _ in _event_type_options()}),
        'quick': _listing.choice_arg('quick', _QUICK_PRESETS),
    }


def _instances_query(filters):
    """(query, order, next3) під фільтри списку проведень.

    Пресети `quick` взаємовиключні й самі задають сортування: «найближчі»
    мають рахуватись від сьогодні вгору, архів -- навпаки.
    """
    query = CourseInstance.query.options(joinedload(CourseInstance.course))
    if filters['q']:
        # Пошук за назвою курсу, темою й місцем: саме так менеджер шукає
        # захід, коли пам'ятає "щось про плазмоліфтинг у Львові". Тема тут
        # нарівні з назвою курсу, бо саме вона стоїть підписом рядка, коли
        # задана -- шукати доводиться по тому, що видно на екрані.
        query = query.join(Course, CourseInstance.course_id == Course.id)
        query = _listing.apply_search(query, filters['q'], [
            Course.title, CourseInstance.topic, CourseInstance.location,
        ])
    if filters['course_id']:
        query = query.filter(CourseInstance.course_id == filters['course_id'])
    if filters['status']:
        query = query.filter(CourseInstance.status == filters['status'])
    if filters['event_type']:
        query = query.filter(_effective_type_clause(filters['event_type']))

    # ----- Таблетки швидких фільтрів (взаємовиключні пресети) -----
    quick = filters['quick']
    now = datetime.now(timezone.utc)
    # Корельовані підзапити: к-сть активних реєстрацій та місткість заходу.
    active_count = (
        db.session.query(func.count(EventRegistration.id))
        .filter(
            EventRegistration.instance_id == CourseInstance.id,
            EventRegistration.status.notin_(['cancelled']),
        )
        .correlate(CourseInstance)
        .scalar_subquery()
    )
    # Місця тримають лише оплачені (services.seating), тож "заповнені" й
    # "є вільні місця" рахуються не так, як "з реєстраціями".
    occupied = (
        db.session.query(func.count(EventRegistration.id))
        .filter(
            EventRegistration.instance_id == CourseInstance.id,
            occupied_clause(),
        )
        .correlate(CourseInstance)
        .scalar_subquery()
    )
    course_max = (
        db.session.query(Course.max_participants)
        .filter(Course.id == CourseInstance.course_id)
        .correlate(CourseInstance)
        .scalar_subquery()
    )
    capacity = func.coalesce(CourseInstance.max_participants, course_max)

    # Вторинний ключ id -- щоб проведення з однаковою датою (а їх багато:
    # кілька курсів в один день) не тасувались між перезавантаженнями. Без
    # нього LIMIT 3 у next3 щоразу міг віддати інші три рядки.
    order = (CourseInstance.start_date.desc(), CourseInstance.id.desc())
    next3 = False

    if quick == 'upcoming':
        query = query.filter(CourseInstance.start_date >= now)
        order = (CourseInstance.start_date.asc(), CourseInstance.id.asc())
    elif quick == 'next3':
        # Лише реальні заходи: чернетки й скасовані займали всі три слоти і
        # витісняли опубліковане проведення того самого дня -- на екран
        # потрапляли чужі лічильники реєстрацій.
        query = query.filter(
            CourseInstance.start_date >= now,
            CourseInstance.status.in_(('published', 'active')),
        )
        order = (CourseInstance.start_date.asc(), CourseInstance.id.asc())
        next3 = True
    elif quick == 'past':
        query = query.filter(CourseInstance.start_date < now)
    elif quick == 'this_month':
        month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        next_year = now.year + (1 if now.month == 12 else 0)
        next_month = 1 if now.month == 12 else now.month + 1
        month_end = datetime(next_year, next_month, 1, tzinfo=timezone.utc)
        query = query.filter(
            CourseInstance.start_date >= month_start,
            CourseInstance.start_date < month_end,
        )
        order = (CourseInstance.start_date.asc(), CourseInstance.id.asc())
    elif quick == 'with_regs':
        query = query.filter(active_count > 0)
    elif quick == 'no_regs':
        query = query.filter(active_count == 0)
    elif quick == 'free_seats':
        query = query.filter(or_(capacity.is_(None), occupied < capacity))
    elif quick == 'full':
        query = query.filter(capacity.isnot(None), occupied >= capacity)
    elif quick == 'attention':
        query = query.filter(
            CourseInstance.start_date >= now,
            CourseInstance.start_date <= now + timedelta(days=14),
            active_count == 0,
        )
        order = (CourseInstance.start_date.asc(), CourseInstance.id.asc())

    return query, order, next3


def _instance_reg_counts(instances):
    """{instance_id: активних реєстрацій} одним запитом.

    Без цього шаблон запускає N+1 COUNT-ів через inst.registration_count
    (lazy='dynamic').
    """
    if not instances:
        return {}
    return dict(
        db.session.query(
            EventRegistration.instance_id,
            func.count(EventRegistration.id),
        )
        .filter(
            EventRegistration.instance_id.in_([i.id for i in instances]),
            EventRegistration.status.notin_(['cancelled']),
        )
        .group_by(EventRegistration.instance_id)
        .all()
    )


@admin_bp.route('/instances')
@permission_required('instances.view')
def instances_list():
    filters = _instance_filters()
    query, order, next3 = _instances_query(filters)

    if next3:
        instances = query.order_by(*order).limit(3).all()
        pagination = None
    else:
        pagination = query.order_by(*order).paginate(
            page=_listing.page_arg(),
            per_page=_INSTANCES_PER_PAGE, error_out=False,
        )
        instances = pagination.items

    return render_template(
        'admin/instances.html',
        instances=instances,
        pagination=pagination,
        reg_counts=_instance_reg_counts(instances),
        # Зайняті місця показуємо окремо від реєстрацій: тримають місце лише
        # оплачені, і саме тут видно перевищення пулу (7/6 червоним).
        occupied_map=occupied_counts([i.id for i in instances]),
        filters=filters,
        filter_args=_listing.filter_args(filters),
        course_options=[
            (c.id, c.title)
            for c in Course.query.filter_by(is_active=True).order_by(Course.title).all()
        ],
        status_options=CourseInstance.STATUSES,
        event_type_options=_event_type_options(),
    )


@admin_bp.route('/instances/report.xlsx')
@permission_required('instances.export')
def instances_report_export():
    """Експорт проведень у xlsx з урахуванням активних фільтрів.

    Це ЗВІТ (з реєстраціями й вільними місцями), а не шаблон імпорту: для
    редагування живе окремий /admin/instances/export із `export_instances_xlsx`
    та парою parse_instances_xlsx -- звідси й різні URL.
    """
    from app.services import xlsx_reports

    filters = _instance_filters()
    query, order, next3 = _instances_query(filters)
    # Тренерів вантажимо САМЕ тут, а не в _instances_query: сторінка розкладу
    # їх не показує (див. admin/instances.html), а звіт кличе
    # effective_trainer на кожному рядку. effective_trainer читає ОБИДВА боки
    # (свій перелік, інакше курсовий), тож без курсових тренерів ми лише
    # пересунули б N+1 з CourseInstance.trainers на Course.trainers.
    # joinedload на course -- той самий шлях, що вже задав _instances_query:
    # дві різні стратегії на одну звʼязку сперечалися б між собою.
    query = query.options(
        joinedload(CourseInstance.course).selectinload(Course.trainers),
        selectinload(CourseInstance.trainers),
    )
    query = query.order_by(*order)
    if next3:
        # Гілка next3 завідомо не більша за три рядки: export_query рахує
        # COUNT по запиту БЕЗ limit і відмовив би експорту, який насправді
        # віддав би три рядки. Стеля тут ні до чого -- лишаємо як є.
        instances = query.limit(3).all()
    else:
        instances, refusal = _listing.export_query(
            query, 'admin.instances_list', **_listing.filter_args(filters),
        )
        if refusal:
            return refusal

    course = (
        db.session.get(Course, filters['course_id'])
        if filters['course_id'] else None
    )
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Курс', course.title if course else 'Усі'),
            ('Статус', dict(CourseInstance.STATUSES).get(filters['status'], 'Усі')),
            ('Вид заходу', event_types.base_name(filters['event_type'])
             if filters['event_type'] else 'Усі'),
            ('Швидкий фільтр', filters['quick'] or '–'),
        ],
        len(instances),
    )
    audit_logger.info(
        'Admin %s exported instances xlsx (%d rows, filters=%s)',
        current_user.email, len(instances), filters,
    )
    return _listing.xlsx_export(
        instances, 'instances',
        lambda: xlsx_reports.export_instances_report_xlsx(
            instances, _instance_reg_counts(instances),
            occupied_counts([i.id for i in instances]), applied_filters=summary),
        'admin.instances_list', **_listing.filter_args(filters),
    )


def _lecturer_certs_by_trainer(instance):
    """Видані сертифікати тренера заходу, за trainer_id -- для рядків у шаблоні.

    Один захід тепер може мати кілька сертифікатів тренера (по одному на
    тренера), тож замість одного запису шаблону потрібен словник.
    """
    from app.models.lecturer_certificate import LecturerCertificate
    rows = LecturerCertificate.query.filter_by(instance_id=instance.id).all()
    return {lc.trainer_id: lc for lc in rows}


def _render_instance_form(form, instance, preselected_course_id=None):
    """Єдиний вхід у шаблон форми проведення.

    Виходів із маршруту редагування три -- GET, невалідна форма і відмова
    гварда статусу, -- і контекст на них мусить бути той самий. Розійтись він
    може рівно доти, доки збирається не в одному місці: саме так на шляху
    помилки вже зникали з форми успадковані значення.
    """
    from app.services import trainer_resume_service as rs

    certs = _lecturer_certs_by_trainer(instance) if instance else {}
    lecturers = instance.effective_trainers if instance else []
    in_lineup = {t.id for t in lecturers}
    return render_template(
        'admin/instance_edit.html',
        form=form,
        instance=instance,
        inherited=_inherited_source(instance, preselected_course_id),
        # Застереження біля поля номера заходу: у щойно створеної дати
        # сертифікатів немає за визначенням, але шаблон один на обидва режими.
        issued_bpr=_issued_bpr(instance),
        lecturers=lecturers,
        lecturer_certs=certs,
        # Сертифікат, виданий тренеру, якого зі складу вже прибрали (або який
        # дістався заходу успадкуванням, а курс потім переграли). Рядка в
        # переліку тренерів у нього немає, але сам документ існує, має номер
        # і вже на руках у людини -- зникнути з адмінки він не може.
        orphan_certs=[lc for tid, lc in certs.items() if tid not in in_lineup],
        resume_columns=rs.available_columns(current_user),
        resume_default_keys=rs.DEFAULT_KEYS,
    )


@admin_bp.route('/instances/new', methods=['GET', 'POST'])
@permission_required('instances.manage')
def instance_create():
    preselected = request.args.get('course_id', type=int)
    form = CourseInstanceForm()
    _populate_choices(form, preselected)

    if form.validate_on_submit():
        instance = CourseInstance()
        course_service.populate_instance_from_form(instance, form)
        db.session.add(instance)
        from app.services import trainer_links
        trainer_links.set_trainers(instance, form.trainer_ids.data)
        # Copy-on-create: дефолтна тарифна вилка курсу переїжджає у
        # проведення (лише шаблони, що пасують формату). flush -- щоб
        # instance отримав id для FK тарифів.
        db.session.flush()
        # Після українського тексту, до коміту: одиниці перекладу рахуються
        # з АКТУАЛЬНОЇ теми, тож тема і її переклад зберігаються одним
        # сабмітом (див. apply_inline_translations).
        apply_inline_translations(instance)
        copied = course_service.copy_course_tariffs_to_instance(instance)
        if try_commit(log_context=f'instance_create course={form.course_id.data}'):
            audit_logger.info(
                'Admin %s created instance %s (course=%s start=%s, tariffs=%s)',
                current_user.email, instance.id, instance.course_id,
                instance.start_date, copied,
            )
            if copied:
                flash(f'Проведення створено, скопійовано тарифів з курсу: {copied}', 'success')
            else:
                flash('Проведення створено', 'success')
            return redirect(url_for('admin.instances_list'))

    return _render_instance_form(form, None, preselected)


@admin_bp.route('/instances/<int:instance_id>/edit', methods=['GET', 'POST'])
@permission_required('instances.manage')
def instance_edit(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    form = CourseInstanceForm(obj=instance)
    _populate_choices(form, instance=instance)

    if request.method == 'GET':
        # Власний перелік проведення, НЕ effective_trainers: порожнє поле
        # означає «успадкувати тренерів курсу», і префіл успадкованим
        # списком непомітно перетворив би успадкування на явну копію
        # при першому ж збереженні форми.
        form.trainer_ids.data = [t.id for t in instance.trainers]

    if form.validate_on_submit():
        try:
            course_service.populate_instance_from_form(instance, form)
        except course_service.InvalidStatusTransition as exc:
            # Найчастіше -- спроба повернути в «Чернетку» проведення, на яке
            # вже записались. Повідомлення гварда написане менеджеру й
            # називає дію («оберіть Скасовано»), тож друкуємо його як є.
            db.session.rollback()
            flash(str(exc), 'error')
            return _render_instance_form(form, instance)
        from app.services import trainer_links
        trainer_links.set_trainers(instance, form.trainer_ids.data)
        apply_inline_translations(instance)
        if try_commit(log_context=f'instance_edit id={instance.id}'):
            audit_logger.info(
                'Admin %s updated instance %s', current_user.email, instance.id,
            )
            flash('Проведення оновлено', 'success')
            return redirect(url_for('admin.instances_list'))

    return _render_instance_form(form, instance)


@admin_bp.route('/instances/<int:instance_id>/lecturer-certificate', methods=['POST'])
@permission_required('instances.manage')
def instance_lecturer_certificate(instance_id):
    """Видати/завантажити сертифікат тренера для проведення (PDF)."""
    import io
    from flask import send_file
    from app.services import certificate_service as cs

    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    # Завантаження вже виданого і видача нового -- дві різні дії, і склад
    # заходу обмежує лише другу. Сертифікат із номером уже на руках у людини:
    # те, що її потім прибрали зі складу, не робить документ недосяжним.
    cert_id = request.form.get('cert_id', type=int)
    if cert_id is not None:
        from app.models.lecturer_certificate import LecturerCertificate
        lc = LecturerCertificate.query.filter_by(
            id=cert_id, instance_id=instance.id,
        ).first()
        if lc is None:
            flash('Сертифікат не знайдено', 'error')
            return redirect(url_for('admin.instance_edit', instance_id=instance_id))
        try:
            pdf = cs.render_lecturer_pdf(lc)
        except Exception:
            current_app.logger.exception('lecturer cert render failed')
            flash('Не вдалося сформувати PDF сертифіката тренера', 'error')
            return redirect(url_for('admin.instance_edit', instance_id=instance_id))
        return send_file(io.BytesIO(pdf), mimetype='application/pdf',
                         as_attachment=True, download_name=f'lecturer-{lc.number}.pdf')

    trainer_id = request.form.get('trainer_id', type=int)
    trainer = next(
        (t for t in instance.effective_trainers if t.id == trainer_id), None
    )
    if trainer is None:
        # Свого тренера серед тренерів заходу -- чужого id (підміна у формі)
        # не приймаємо, так само як відсутність вибору.
        flash('Оберіть тренера зі списку тренерів заходу', 'error')
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))

    try:
        lc = cs.issue_lecturer_certificate(instance, trainer, issued_by=current_user)
        pdf = cs.render_lecturer_pdf(lc)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))
    except Exception:
        current_app.logger.exception('lecturer cert generation failed')
        flash('Не вдалося згенерувати сертифікат тренера', 'error')
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))

    audit_logger.info('Admin %s issued lecturer cert %s instance=%s',
                      current_user.email, lc.number, instance_id)
    return send_file(io.BytesIO(pdf), mimetype='application/pdf',
                     as_attachment=True, download_name=f'lecturer-{lc.number}.pdf')


@admin_bp.route('/instances/<int:instance_id>/lecturer-certificate/reissue',
                methods=['POST'])
@permission_required('instances.manage')
def instance_lecturer_certificate_reissue(instance_id):
    """Перевидати сертифікат тренера за поточними даними й віддати PDF.

    Потрібне після виправлення номера заходу в проведенні: видача номер
    уже виданого серта не переписує (див. certificate_service.reissue_*).

    Адресуємо саме сертифікат (`cert_id`), а не тренера, і тренера беремо з
    нього: у заходу їх кілька, а склад заходу з часом міняється -- виданий
    документ мусить лишатись перевидаваним і після того, як людину зі
    складу прибрали (та сама межа, що й у завантаженні вище).
    """
    import io
    from flask import send_file
    from app.models.lecturer_certificate import LecturerCertificate
    from app.services import certificate_service as cs

    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    cert_id = request.form.get('cert_id', type=int)
    lc = LecturerCertificate.query.filter_by(
        id=cert_id, instance_id=instance.id,
    ).first() if cert_id is not None else None
    if lc is None:
        flash('Сертифікат не знайдено', 'error')
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))

    try:
        lc = cs.reissue_lecturer_certificate(
            instance, lc.trainer, issued_by=current_user,
        )
        pdf = cs.render_lecturer_pdf(lc)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))
    except Exception:
        current_app.logger.exception('lecturer cert reissue failed')
        flash('Не вдалося перевидати сертифікат тренера', 'error')
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))

    audit_logger.info('Admin %s reissued lecturer cert %s instance=%s trainer=%s',
                      current_user.email, lc.number, instance_id, lc.trainer_id)
    return send_file(io.BytesIO(pdf), mimetype='application/pdf',
                     as_attachment=True, download_name=f'lecturer-{lc.number}.pdf')


@admin_bp.route('/instances/<int:instance_id>/status', methods=['POST'])
@permission_required('instances.manage')
@limiter.limit('60 per minute')
def instance_status_update(instance_id):
    wants_json = _wants_json()
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        if wants_json:
            return jsonify({'ok': False, 'error': 'Проведення не знайдено'}), 404
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    new_status = (request.form.get('status') or '').strip()

    try:
        old_status, _ = course_service.change_instance_status(instance, new_status)
    except InvalidStatusTransition as exc:
        if wants_json:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        flash(str(exc), 'error')
        return redirect(url_for('admin.instances_list'))

    if old_status == new_status:
        if wants_json:
            return jsonify({
                'ok': True,
                'status': instance.status,
                'status_label': instance.status_label,
            })
        return redirect(url_for('admin.instances_list'))

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to update instance %s status', instance_id)
        if wants_json:
            return jsonify({'ok': False, 'error': 'Помилка при збереженні'}), 500
        flash('Помилка при збереженні', 'error')
        return redirect(url_for('admin.instances_list'))

    audit_logger.info(
        'Admin %s changed instance %s status: %s -> %s',
        current_user.email, instance_id, old_status, new_status,
    )

    # Сертифікати тренерам -- рівно на переході в 'completed'. Лише INSERT:
    # рендер PDF і лист робить фонова джоба, тож адмін не чекає WeasyPrint,
    # а збій рендера не відкочує зміну статусу.
    if new_status == 'completed' and old_status != 'completed':
        from app.services import lecturer_certificates as lc_svc
        lc_svc.issue_for_instance(instance, issued_by=current_user)

    if wants_json:
        return jsonify({
            'ok': True,
            'status': instance.status,
            'status_label': instance.status_label,
        })
    flash(f'Статус змінено на "{instance.status_label}"', 'success')
    return redirect(url_for('admin.instances_list'))


@admin_bp.route('/instances/<int:instance_id>/delete', methods=['POST'])
@permission_required('instances.delete')
def instance_delete(instance_id):
    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    db.session.delete(instance)
    if try_commit(
        log_context=f'instance_delete id={instance_id}',
        error_msg='Помилка при видаленні',
    ):
        audit_logger.info(
            'Admin %s deleted instance %s', current_user.email, instance_id,
        )
        flash('Проведення видалено', 'success')
    return redirect(url_for('admin.instances_list'))
