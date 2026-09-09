"""Адмінка довідника видів заходів БПР.

Довідник плоский і на півтора десятка рядків, тож окремої сторінки
редагування немає: уся таблиця правиться і зберігається одним сабмітом --
той самий підхід, що в довіднику локацій.

Вживаний тип не видаляється, а деактивується. Інакше зміна номенклатури
лишила б курси з кодом, якого вже ніде немає, і вони показували б голий
латинський рядок замість назви.
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin._helpers import try_commit
from app.extensions import db
from app.i18n import PREFIXED_LANGUAGES
from app.models.event_type import EventType
from app.rbac import permission_required
from app.services import event_types

audit_logger = logging.getLogger('audit')


def _rows():
    """Рядок таблиці збираємо тут, а не в шаблоні: розкопувати JSON
    перекладів у Jinja -- логіка не на своєму поверсі."""
    usage = event_types.usage()
    rows = []
    for row in EventType.query.order_by(EventType.sort_order, EventType.name).all():
        stored = row.translations or {}
        # Ключ саме 'tr': row.values у Jinja дало б метод dict.values.
        rows.append({
            'type': row,
            'tr': {lang: ((stored.get(lang) or {}).get('name') or '')
                   for lang in PREFIXED_LANGUAGES},
            'uses': usage.get(row.code, 0),
        })
    return rows


@admin_bp.route('/event-types', methods=['GET'])
@permission_required('event_types.view')
def event_types_list():
    rows = _rows()
    return render_template(
        'admin/event_types.html',
        rows=rows,
        languages=PREFIXED_LANGUAGES,
        active_count=sum(1 for r in rows if r['type'].is_active),
    )


@admin_bp.route('/event-types/save', methods=['POST'])
@permission_required('event_types.manage')
def event_types_save():
    """Зберегти всю таблицю одним сабмітом."""
    changed = 0
    for row in EventType.query.all():
        name_key = f'name__{row.id}'
        if name_key not in request.form:
            continue
        name = (request.form.get(name_key) or '').strip()
        if name:
            row.name = name
        row.name_accusative = (request.form.get(f'accusative__{row.id}') or '').strip() or None
        row.name_genitive = (request.form.get(f'genitive__{row.id}') or '').strip() or None
        try:
            row.sort_order = int(request.form.get(f'sort__{row.id}') or row.sort_order)
        except ValueError:
            pass
        # Незнята галка чекбокса просто не приходить у form -- саме так
        # рядок і деактивують.
        row.is_active = f'active__{row.id}' in request.form
        for lang in PREFIXED_LANGUAGES:
            row.set_translation(
                lang, 'name',
                (request.form.get(f'tr__{lang}__{row.id}') or '').strip() or None,
            )
        changed += 1

    if try_commit(log_context='event_types_save'):
        event_types.reset_cache()
        audit_logger.info('Admin %s updated event type directory (%s rows)',
                          current_user.email, changed)
        flash('Довідник збережено.', 'success')
    return redirect(url_for('admin.event_types_list'))


@admin_bp.route('/event-types/add', methods=['POST'])
@permission_required('event_types.manage')
def event_types_add():
    code = (request.form.get('code') or '').strip().lower()
    name = (request.form.get('name') or '').strip()
    if not code or not name:
        flash('Вкажіть і код, і назву типу', 'error')
        return redirect(url_for('admin.event_types_list'))

    if EventType.query.filter_by(code=code).first():
        flash(f'Тип з кодом "{code}" уже є в довіднику', 'info')
        return redirect(url_for('admin.event_types_list'))

    last = db.session.query(db.func.max(EventType.sort_order)).scalar() or 0
    db.session.add(EventType(
        code=code,
        name=name,
        name_accusative=(request.form.get('accusative') or '').strip() or None,
        name_genitive=(request.form.get('genitive') or '').strip() or None,
        sort_order=last + 1,
        is_active=True,
    ))
    if try_commit(log_context=f'event_types_add code={code!r}',
                  error_msg='Не вдалося додати тип (можливо, його щойно '
                            'додав інший адміністратор)'):
        event_types.reset_cache()
        audit_logger.info('Admin %s added event type %r', current_user.email, code)
        flash(f'Додано "{name}". Впишіть відмінки й переклади та збережіть.', 'success')
    return redirect(url_for('admin.event_types_list'))


@admin_bp.route('/event-types/<int:type_id>/delete', methods=['POST'])
@permission_required('event_types.delete')
def event_types_delete(type_id):
    row = db.session.get(EventType, type_id)
    if row is None:
        flash('Тип не знайдено', 'error')
        return redirect(url_for('admin.event_types_list'))

    uses = event_types.usage().get(row.code, 0)
    if uses:
        flash(f'"{row.name}" вживається у {uses} курсах і проведеннях. '
              f'Зніміть галку «Активний» замість видалення.', 'error')
        return redirect(url_for('admin.event_types_list'))

    name = row.name
    db.session.delete(row)
    if try_commit(log_context=f'event_types_delete id={type_id}'):
        event_types.reset_cache()
        audit_logger.info('Admin %s deleted event type %r', current_user.email, name)
        flash(f'"{name}" видалено з довідника.', 'success')
    return redirect(url_for('admin.event_types_list'))
