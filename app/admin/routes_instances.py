"""Admin CRUD для CourseInstance (проведення)."""
import logging
from datetime import datetime, timedelta, timezone

from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import current_user
from sqlalchemy import func, or_
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
from app.services import course_service
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
        empty_label='– Як у курсу –',
    )


_INSTANCES_PER_PAGE = 25


_QUICK_PRESETS = (
    'upcoming', 'next3', 'past', 'this_month', 'with_regs',
    'no_regs', 'free_seats', 'full', 'attention',
)


def _instance_filters():
    """Фільтри списку проведень -- спільні для сторінки й експорту."""
    return {
        'q': _listing.text_arg('q'),
        'course_id': _listing.int_arg('course_id'),
        'status': _listing.choice_arg('status', dict(CourseInstance.STATUSES)),
        'quick': _listing.choice_arg('quick', _QUICK_PRESETS),
    }


def _instances_query(filters):
    """(query, order, next3) під фільтри списку проведень.

    Пресети `quick` взаємовиключні й самі задають сортування: «найближчі»
    мають рахуватись від сьогодні вгору, архів -- навпаки.
    """
    query = CourseInstance.query.options(
        # effective_trainer читає ОБИДВА боки (свій перелік, інакше --
        # курсовий): без селекту курсових тренерів тут ми лише пересунули
        # б N+1 з CourseInstance.trainer на Course.trainers.
        joinedload(CourseInstance.course).selectinload(Course.trainers),
        selectinload(CourseInstance.trainers),
    )
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
        # Після українського тексту, до коміту: одиниці перекладу рахуються
        # з АКТУАЛЬНОЇ теми, тож тема і її переклад зберігаються одним
        # сабмітом (див. apply_inline_translations).
        # Copy-on-create: дефолтна тарифна вилка курсу переїжджає у
        # проведення (лише шаблони, що пасують формату). flush -- щоб
        # instance отримав id для FK тарифів.
        db.session.flush()
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

    return render_template('admin/instance_edit.html', form=form, instance=None)


def _lecturer_certs_by_trainer(instance):
    """Видані сертифікати лектора заходу, за trainer_id -- для рядків у шаблоні.

    Один захід тепер може мати кілька лекторських сертифікатів (по одному на
    тренера), тож замість одного запису шаблону потрібен словник.
    """
    from app.models.lecturer_certificate import LecturerCertificate
    rows = LecturerCertificate.query.filter_by(instance_id=instance.id).all()
    return {lc.trainer_id: lc for lc in rows}


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
            return render_template('admin/instance_edit.html', form=form,
                                   instance=instance,
                                   lecturer_certs=_lecturer_certs_by_trainer(instance))
        from app.services import trainer_links
        trainer_links.set_trainers(instance, form.trainer_ids.data)
        apply_inline_translations(instance)
        if try_commit(log_context=f'instance_edit id={instance.id}'):
            audit_logger.info(
                'Admin %s updated instance %s', current_user.email, instance.id,
            )
            flash('Проведення оновлено', 'success')
            return redirect(url_for('admin.instances_list'))

    return render_template('admin/instance_edit.html', form=form, instance=instance,
                           lecturer_certs=_lecturer_certs_by_trainer(instance))


@admin_bp.route('/instances/<int:instance_id>/lecturer-certificate', methods=['POST'])
@permission_required('instances.manage')
def instance_lecturer_certificate(instance_id):
    """Видати/завантажити сертифікат лектора для проведення (PDF)."""
    import io
    from flask import send_file
    from app.services import certificate_service as cs

    instance = db.session.get(CourseInstance, instance_id)
    if not instance:
        flash('Проведення не знайдено', 'error')
        return redirect(url_for('admin.instances_list'))

    trainer_id = request.form.get('trainer_id', type=int)
    trainer = next(
        (t for t in instance.effective_trainers if t.id == trainer_id), None
    )
    if trainer is None:
        # Свого тренера серед тренерів заходу -- чужого id (підміна у формі)
        # не приймаємо, так само як відсутність вибору.
        flash('Оберіть лектора зі списку тренерів заходу', 'error')
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))

    try:
        lc = cs.issue_lecturer_certificate(instance, trainer, issued_by=current_user)
        pdf = cs.render_lecturer_pdf(lc)
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))
    except Exception:
        current_app.logger.exception('lecturer cert generation failed')
        flash('Не вдалося згенерувати сертифікат лектора', 'error')
        return redirect(url_for('admin.instance_edit', instance_id=instance_id))

    audit_logger.info('Admin %s issued lecturer cert %s instance=%s',
                      current_user.email, lc.number, instance_id)
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
