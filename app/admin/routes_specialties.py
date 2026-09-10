"""Адмінка довідника спеціальностей: назва, розділ, переклади, порядок,
активність -- одна таблиця, один сабміт.

Рядків тут дві сотні, тож над таблицею стоять пошук, фільтр за розділом і
фільтр за станом (активна/деактивована). Збереження читає ТІЛЬКИ ті ключі
форми, що прийшли, тож збереження відфільтрованої таблиці не чіпає решту
довідника.
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.admin._helpers import try_commit
from app.extensions import db
from app.i18n import PREFIXED_LANGUAGES
from app.models.specialty import SECTIONS, SECTION_LABELS, Specialty
from app.rbac import permission_required
from app.services import specialties as specialties_service

audit_logger = logging.getLogger('audit')

# Той самий словник станів, що й у довідниках курсів/тренерів (routes_courses,
# routes_trainers): не "is_active" галкою у фільтрі, а звична пара станів.
_STATES = {'active': 'Активні', 'inactive': 'Деактивовані'}


@admin_bp.route('/specialties', methods=['GET'])
@permission_required('specialties.view')
def specialties_list():
    filters = {
        'q': _listing.text_arg('q'),
        'section': _listing.choice_arg('section', SECTION_LABELS),
        'state': _listing.choice_arg('state', _STATES),
    }
    query = Specialty.query
    if filters['section']:
        query = query.filter(Specialty.section == filters['section'])
    if filters['state']:
        query = query.filter(Specialty.is_active.is_(filters['state'] == 'active'))
    query = _listing.apply_search(query, filters['q'], [Specialty.name, Specialty.code])
    items = query.order_by(Specialty.section, Specialty.sort_order, Specialty.name).all()

    usage = specialties_service.usage()
    rows = []
    for specialty in items:
        stored = specialty.translations or {}
        # Ключ саме 'tr': row.values у Jinja дало б метод dict.values.
        translations = {lang: ((stored.get(lang) or {}).get('name') or '')
                        for lang in PREFIXED_LANGUAGES}
        rows.append({
            'specialty': specialty,
            'tr': translations,
            'uses': usage.get(specialty.code, 0),
        })

    # Лічильники зверху рахуються від УСЬОГО довідника, а не від показаного
    # зрізу: інакше картка "Активних: N" стрибала б разом із пошуком і не
    # відповідала б на власне питання "скільки в довіднику взагалі".
    total = Specialty.query.count()
    active_count = Specialty.query.filter_by(is_active=True).count()

    return render_template(
        'admin/specialties.html',
        rows=rows,
        sections=SECTIONS,
        section_options=list(SECTION_LABELS.items()),
        state_options=list(_STATES.items()),
        languages=PREFIXED_LANGUAGES,
        total=total,
        active_count=active_count,
        inactive_count=total - active_count,
        filters=filters,
        filter_args=_listing.filter_args(filters),
    )


@admin_bp.route('/specialties/save', methods=['POST'])
@permission_required('specialties.manage')
def specialties_save():
    """Зберегти показані рядки. Ключі, яких у формі немає, не чіпаються."""
    touched = 0
    for specialty in Specialty.query.all():
        marker = f'row__{specialty.id}'
        if marker not in request.form:
            continue
        touched += 1
        for lang in PREFIXED_LANGUAGES:
            value = (request.form.get(f'tr__{lang}__{specialty.id}') or '').strip()
            specialty.set_translation(lang, 'name', value or None)
        order = (request.form.get(f'order__{specialty.id}') or '').strip()
        if order.isdigit():
            specialty.sort_order = int(order)
        # Чекбокс приходить лише коли ввімкнений -- саме так знімають рядок.
        specialty.is_active = f'active__{specialty.id}' in request.form

    if try_commit(log_context='specialties_save'):
        audit_logger.info('Admin %s updated specialties (%s rows)',
                          current_user.email, touched)
        flash('Довідник збережено.', 'success')
    return redirect(url_for('admin.specialties_list'))


@admin_bp.route('/specialties/add', methods=['POST'])
@permission_required('specialties.manage')
def specialties_add():
    name = (request.form.get('name') or '').strip()
    section = request.form.get('section') or ''
    if not name or section not in SECTION_LABELS:
        flash('Вкажіть назву і розділ', 'error')
        return redirect(url_for('admin.specialties_list'))

    taken = {row.code for row in Specialty.query.all()}
    code = specialties_service.specialty_code(name, taken=taken)
    last = (Specialty.query.filter_by(section=section)
            .order_by(Specialty.sort_order.desc()).first())
    db.session.add(Specialty(
        code=code, name=name, section=section,
        sort_order=(last.sort_order + 1) if last else 1,
    ))
    if try_commit(log_context=f'specialties_add name={name!r}'):
        audit_logger.info('Admin %s added specialty %r (%s)',
                          current_user.email, name, code)
        flash(f'Додано "{name}". Впишіть переклади і збережіть.', 'success')
    return redirect(url_for('admin.specialties_list', **_listing.filter_args({})))


@admin_bp.route('/specialties/<int:specialty_id>/delete', methods=['POST'])
@permission_required('specialties.delete')
def specialties_delete(specialty_id):
    specialty = db.session.get(Specialty, specialty_id)
    if specialty is None:
        flash('Спеціальність не знайдено', 'error')
        return redirect(url_for('admin.specialties_list'))

    uses = specialties_service.usage().get(specialty.code, 0)
    if uses:
        # Видалити зайнятий рядок означало б лишити курси з осиротілим кодом.
        flash(f'"{specialty.name}" вживається у {uses} курсах/проведеннях. '
              f'Зніміть галку «Активна» замість видалення.', 'error')
        return redirect(url_for('admin.specialties_list'))

    name = specialty.name
    db.session.delete(specialty)
    if try_commit(log_context=f'specialties_delete id={specialty_id}'):
        audit_logger.info('Admin %s deleted specialty %r', current_user.email, name)
        flash(f'"{name}" видалено з довідника.', 'success')
    return redirect(url_for('admin.specialties_list'))
