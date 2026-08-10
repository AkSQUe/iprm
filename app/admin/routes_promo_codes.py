"""Admin CRUD промокодів + історія використань.

Кейси, під які це робилось: персональна знижка (тренер просить за колегу),
безкоштовна реєстрація "забутого" учасника, B2B-пакет для фарми
("5 місць на цей захід"), бонус клініці за закупівлю, тест механіки
реєстрації та автолистів.
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import _listing, admin_bp
from app.admin._helpers import try_commit
from app.admin.decorators import admin_required
from app.admin.forms import PromoCodeForm
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.promo_code import PromoCode
from app.services import participant_service, promo_service
from app.utils import ensure_utc

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

PER_PAGE = 30


def _populate_scope_choices(form):
    """Курси та проведення для полів звуження області дії."""
    courses = Course.query.order_by(Course.title).all()
    form.course_id.choices = [('', '— усі курси —')] + [
        (str(c.id), c.title) for c in courses
    ]
    instances = (
        db.session.query(CourseInstance)
        .options(joinedload(CourseInstance.course))
        .order_by(CourseInstance.start_date.desc().nullslast())
        .limit(300)
        .all()
    )
    form.instance_id.choices = [('', '— усі проведення —')] + [
        (str(i.id), participant_service.event_label(i, with_id=True))
        for i in instances
    ]


def _form_to_promo(form, promo):
    """Перенести дані форми в модель. Не комітить."""
    promo.code = form.code.data.strip()
    promo.code_norm = promo_service.normalize_code(form.code.data)
    promo.description = (form.description.data or '').strip() or None
    promo.discount_type = form.discount_type.data
    promo.discount_value = form.discount_value.data
    promo.max_uses = form.max_uses.data or None
    promo.per_user_limit = form.per_user_limit.data or None
    # DateTimeLocalField віддає naive-datetime у локальному часі браузера;
    # зберігаємо в UTC, як решта дат у проєкті.
    promo.valid_from = ensure_utc(form.valid_from.data)
    promo.valid_until = ensure_utc(form.valid_until.data)
    # Прив'язка до проведення вужча за прив'язку до курсу -- якщо обрані
    # обидві, курс лишаємо порожнім, щоб не було двох правил на один код.
    instance_id = int(form.instance_id.data) if form.instance_id.data else None
    course_id = int(form.course_id.data) if form.course_id.data else None
    promo.instance_id = instance_id
    promo.course_id = None if instance_id else course_id
    promo.is_active = form.is_active.data


def _code_taken(code_norm, exclude_id=None):
    q = PromoCode.query.filter_by(code_norm=code_norm)
    if exclude_id is not None:
        q = q.filter(PromoCode.id != exclude_id)
    return q.first() is not None


_PROMO_STATES = {'active': 'Активні', 'disabled': 'Вимкнені'}


def _promo_filters():
    """Фільтри списку промокодів -- спільні для сторінки й експорту."""
    return {
        'q': _listing.text_arg('q'),
        'status': _listing.choice_arg('status', _PROMO_STATES),
    }


def _promo_query(filters):
    """Промокоди під фільтри, найновіші першими."""
    query = PromoCode.query.options(
        joinedload(PromoCode.course),
        joinedload(PromoCode.instance).joinedload(CourseInstance.course),
    )
    # Пошук через спільний хелпер: він екранує % і _, інакше код зі знаком
    # відсотка в описі перетворював фільтр на "показати все".
    query = _listing.apply_search(query, filters['q'], [
        PromoCode.code, PromoCode.description,
    ])
    if filters['status']:
        query = query.filter(
            PromoCode.is_active.is_(filters['status'] == 'active'))
    return query.order_by(PromoCode.created_at.desc())


@admin_bp.route('/promo-codes')
@admin_required
def promo_codes_list():
    filters = _promo_filters()
    pagination = _promo_query(filters).paginate(
        page=request.args.get('page', 1, type=int),
        per_page=PER_PAGE, error_out=False,
    )
    return render_template(
        'admin/promo_codes.html',
        pagination=pagination,
        promos=pagination.items,
        filters=filters,
        filter_args=_listing.filter_args(filters),
        status_options=list(_PROMO_STATES.items()),
    )


@admin_bp.route('/promo-codes/export')
@admin_required
def promo_codes_export():
    """Експорт промокодів у xlsx з урахуванням активних фільтрів."""
    from app.services import xlsx_reports

    filters = _promo_filters()
    promos = _promo_query(filters).all()
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '--'),
            ('Стан', _PROMO_STATES.get(filters['status'], 'Усі')),
        ],
        len(promos),
    )
    audit_logger.info(
        'Admin %s exported promo codes xlsx (%d rows, filters=%s)',
        current_user.email, len(promos), filters,
    )
    return _listing.xlsx_export(
        promos, 'promo-codes',
        lambda: xlsx_reports.export_promo_codes_xlsx(promos, applied_filters=summary),
        'admin.promo_codes_list', **_listing.filter_args(filters),
    )


def _create_batch(form, count):
    """Пакет кодів зі спільними налаштуваннями: поле «Промокод» -- префікс.

    Після створення показуємо список, відфільтрований цим самим префіксом --
    так менеджер одразу бачить (і може скопіювати) весь пакет.
    """
    template = PromoCode(created_by_id=current_user.id)
    _form_to_promo(form, template)
    prefix = template.code
    fields = {
        'description': template.description,
        'discount_type': template.discount_type,
        'discount_value': template.discount_value,
        'max_uses': template.max_uses,
        'per_user_limit': template.per_user_limit,
        'valid_from': template.valid_from,
        'valid_until': template.valid_until,
        'course_id': template.course_id,
        'instance_id': template.instance_id,
        'is_active': template.is_active,
        'created_by_id': current_user.id,
    }
    try:
        codes = promo_service.generate_batch(count, prefix=prefix, **fields)
    except promo_service.PromoError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return render_template('admin/promo_code_edit.html', form=form, promo=None)

    if try_commit(f'promo_codes_batch {prefix} x{count}'):
        audit_logger.info(
            'Admin %s created %s promo codes with prefix "%s" (%s)',
            current_user.email, len(codes), prefix, template.discount_label,
        )
        flash(f'Створено кодів: {len(codes)}', 'success')
        return redirect(url_for('admin.promo_codes_list', q=prefix))
    return render_template('admin/promo_code_edit.html', form=form, promo=None)


@admin_bp.route('/promo-codes/new', methods=['GET', 'POST'])
@admin_required
def promo_code_create():
    form = PromoCodeForm()
    _populate_scope_choices(form)

    if form.validate_on_submit():
        code_norm = promo_service.normalize_code(form.code.data)
        if not code_norm:
            flash('Код не може складатись лише з пробілів', 'error')
            return render_template('admin/promo_code_edit.html', form=form, promo=None)

        batch_count = form.batch_count.data or 1
        if batch_count > 1:
            return _create_batch(form, batch_count)

        if _code_taken(code_norm):
            flash('Такий промокод уже існує', 'error')
            return render_template('admin/promo_code_edit.html', form=form, promo=None)

        promo = PromoCode(created_by_id=current_user.id)
        _form_to_promo(form, promo)
        db.session.add(promo)
        if try_commit(f'promo_code_create {promo.code}'):
            audit_logger.info(
                'Admin %s created promo code "%s" (%s, max_uses=%s, scope=%s)',
                current_user.email, promo.code, promo.discount_label,
                promo.max_uses, promo.scope_label,
            )
            flash('Промокод створено', 'success')
            return redirect(url_for('admin.promo_code_detail', promo_id=promo.id))

    return render_template('admin/promo_code_edit.html', form=form, promo=None)


@admin_bp.route('/promo-codes/<int:promo_id>/edit', methods=['GET', 'POST'])
@admin_required
def promo_code_edit(promo_id):
    promo = db.session.get(PromoCode, promo_id)
    if promo is None:
        flash('Промокод не знайдено', 'error')
        return redirect(url_for('admin.promo_codes_list'))

    form = PromoCodeForm(obj=promo)
    _populate_scope_choices(form)
    if request.method == 'GET':
        form.course_id.data = str(promo.course_id) if promo.course_id else ''
        form.instance_id.data = str(promo.instance_id) if promo.instance_id else ''

    if form.validate_on_submit():
        code_norm = promo_service.normalize_code(form.code.data)
        if not code_norm:
            flash('Код не може складатись лише з пробілів', 'error')
            return render_template('admin/promo_code_edit.html', form=form, promo=promo)
        if _code_taken(code_norm, exclude_id=promo.id):
            flash('Такий промокод уже існує', 'error')
            return render_template('admin/promo_code_edit.html', form=form, promo=promo)

        # Ліміт нижчий за вже витрачене -- код просто стає вичерпаним;
        # відбирати знижку в тих, хто вже зареєструвався, ми не будемо.
        if form.max_uses.data and form.max_uses.data < (promo.used_count or 0):
            flash(
                f'Ліміт менший за вже використані {promo.used_count} — '
                'код одразу стане вичерпаним', 'info',
            )

        _form_to_promo(form, promo)
        if try_commit(f'promo_code_edit {promo.id}'):
            audit_logger.info(
                'Admin %s updated promo code #%s ("%s")',
                current_user.email, promo.id, promo.code,
            )
            flash('Промокод оновлено', 'success')
            return redirect(url_for('admin.promo_code_detail', promo_id=promo.id))

    return render_template('admin/promo_code_edit.html', form=form, promo=promo)


@admin_bp.route('/promo-codes/<int:promo_id>')
@admin_required
def promo_code_detail(promo_id):
    promo = db.session.query(PromoCode).options(
        joinedload(PromoCode.course),
        joinedload(PromoCode.instance).joinedload(CourseInstance.course),
    ).filter_by(id=promo_id).first()
    if promo is None:
        flash('Промокод не знайдено', 'error')
        return redirect(url_for('admin.promo_codes_list'))

    return render_template(
        'admin/promo_code_detail.html',
        promo=promo,
        stats=promo_service.stats(promo),
        redemptions=promo_service.list_redemptions(promo),
    )


@admin_bp.route('/promo-codes/<int:promo_id>/toggle', methods=['POST'])
@admin_required
def promo_code_toggle(promo_id):
    promo = db.session.get(PromoCode, promo_id)
    if promo is None:
        flash('Промокод не знайдено', 'error')
        return redirect(url_for('admin.promo_codes_list'))

    promo.is_active = not promo.is_active
    if try_commit(f'promo_code_toggle {promo.id}'):
        audit_logger.info(
            'Admin %s %s promo code "%s"',
            current_user.email,
            'enabled' if promo.is_active else 'disabled', promo.code,
        )
        flash('Промокод увімкнено' if promo.is_active else 'Промокод вимкнено',
              'success')
    return redirect(request.referrer or url_for('admin.promo_codes_list'))


@admin_bp.route('/promo-codes/<int:promo_id>/recount', methods=['POST'])
@admin_required
def promo_code_recount(promo_id):
    """Перерахувати лічильник з реєстру застосувань.

    Потрібно рідко (ручні правки в БД, історичні рядки), але дешевше, ніж
    гадати, чому "використано 3 з 2".
    """
    promo = db.session.get(PromoCode, promo_id)
    if promo is None:
        flash('Промокод не знайдено', 'error')
        return redirect(url_for('admin.promo_codes_list'))

    actual = promo_service.recount(promo)
    if try_commit(f'promo_code_recount {promo.id}'):
        flash(f'Лічильник перераховано: {actual}', 'success')
    return redirect(url_for('admin.promo_code_detail', promo_id=promo.id))


@admin_bp.route('/promo-codes/<int:promo_id>/delete', methods=['POST'])
@admin_required
def promo_code_delete(promo_id):
    """Видалити код. Реєстрації зберігають знімок знижки (FK SET NULL),
    історія застосувань іде разом із кодом (CASCADE)."""
    promo = db.session.get(PromoCode, promo_id)
    if promo is None:
        flash('Промокод не знайдено', 'error')
        return redirect(url_for('admin.promo_codes_list'))

    code = promo.code
    db.session.delete(promo)
    if try_commit(f'promo_code_delete {promo_id}'):
        audit_logger.info('Admin %s deleted promo code "%s"',
                          current_user.email, code)
        flash('Промокод видалено', 'success')
    return redirect(url_for('admin.promo_codes_list'))
