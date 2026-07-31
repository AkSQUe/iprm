"""Адмін-редактор перекладів контенту БД (ru/en).

Універсальна сторінка /admin/translations/<entity>/<id>: для кожної
перекладної одиниці показує український оригінал (read-only) і поля вводу
для ru/en. Порожнє значення видаляє переклад -> фолбек на укр.

Перелік одиниць і запис перекладів -- у app.services.translation_registry;
цей модуль лише зв'язує його з HTTP-формою. JSON-поля (faq, регалії, блоки
блогу, items) редагуються "поле-проти-поля": структура розбирається на
текстові фрагменти, технічні ключі й розмітка недоторкані.

Імена інпутів:
    <lang>__<поле>              -- скалярне поле
    <lang>__<поле>__<хеш>       -- листок JSON-структури
Хеш -- це source_key українського джерела, тож перестановка елементів
структури не збиває прив'язку перекладу.
"""
from flask import abort, flash, redirect, render_template, request, url_for

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.i18n import PREFIXED_LANGUAGES
from app.services import translation_registry as registry


def _form_name(lang, unit):
    """Ім'я інпута для одиниці перекладу в заданій мові."""
    if unit.is_json_leaf:
        return f'{lang}__{unit.field}__{unit.src_key}'
    return f'{lang}__{unit.field}'


def _build_fields(obj):
    """Метадані полів для шаблону: оригінал + поточні переклади.

    Порядок -- як в __translatable__; JSON-поле без жодного текстового
    листка показуємо порожнім, інакше адмін не зрозуміє, куди воно зникло.
    """
    def entry_for(unit):
        return {
            'uk': unit.source,
            'trans': {
                lang: registry.stored_value(obj, lang, unit)
                for lang in PREFIXED_LANGUAGES
            },
            'names': {lang: _form_name(lang, unit) for lang in PREFIXED_LANGUAGES},
        }

    units_by_field = {}
    for unit in registry.units(obj):
        units_by_field.setdefault(unit.field, []).append(unit)

    fields = []
    for field in obj.__translatable__:
        field_units = units_by_field.get(field, [])
        if registry.widget_for(type(obj), field) == 'json':
            leaves = []
            for unit in field_units:
                leaf = entry_for(unit)
                leaf['rows'] = min(8, max(2, len(unit.source) // 70 + 1))
                leaves.append(leaf)
            fields.append({
                'name': field, 'label': registry.field_label(field),
                'widget': 'json', 'leaves': leaves,
            })
            continue
        unit = field_units[0]
        fields.append({
            **entry_for(unit),
            'name': field, 'label': unit.label, 'widget': unit.widget,
        })
    return fields


def _children_sections(entity, obj):
    """Для курсу -- лінки на переклади дочірніх сутностей (блоки, тарифи)."""
    if entity != 'course':
        return []
    return [
        {
            'title': 'Блоки програми',
            'items': [
                {'entity': 'program_block', 'id': b.id, 'name': b.heading,
                 'done': registry.coverage_label(b)}
                for b in sorted(obj.program_blocks, key=lambda b: b.sort_order or 0)
            ],
        },
        {
            'title': 'Тарифи курсу (шаблони)',
            'items': [
                {'entity': 'course_tariff', 'id': t.id, 'name': t.name,
                 'done': registry.coverage_label(t)}
                for t in obj.default_tariffs
            ],
        },
    ]


def inline_name(lang, unit, prefix='tr'):
    """Ім'я інпута інлайн-вкладки:
        tr__ru__title                  -- скалярне поле
        tr__ru__faq__9c1f2a3b4d5e      -- фрагмент JSON-поля
    Префікс дозволяє покласти в одну форму кілька сутностей (напр. блоки
    програми в формі курсу: trblk__<id>__ru__heading).
    """
    if unit.is_json_leaf:
        return f'{prefix}__{lang}__{unit.field}__{unit.src_key}'
    return f'{prefix}__{lang}__{unit.field}'


def apply_inline_translations(obj, form=None, prefix='tr'):
    """Зберегти переклади з інлайн-вкладок адмін-форм.

    Викликається в POST-обробниках ПІСЛЯ створення/наповнення obj, до
    commit (commit -- на caller-ові). Порядок важливий: спершу зберігається
    український контент, і лише потім переклади, бо одиниці рахуються з
    АКТУАЛЬНОЇ структури. Тому текст і його переклад можна правити одним
    сабмітом: переклад застосується, якщо його джерело вціліло.

    Поля, чиїх інпутів у формі немає, не чіпаються -- форми з частковим
    набором полів безпечні.
    """
    form = form if form is not None else request.form
    all_units = registry.units(obj)
    for lang in PREFIXED_LANGUAGES:
        values = {}
        for unit in all_units:
            key = inline_name(lang, unit, prefix)
            if key in form:
                values[unit.uid] = form.get(key) or ''
        if values:
            registry.apply_units(obj, lang, values)
    return []


@admin_bp.route('/translations/<entity>/<int:obj_id>', methods=['GET', 'POST'])
@admin_required
def translations_edit(entity, obj_id):
    meta = registry.entity_registry().get(entity)
    if meta is None:
        abort(404)
    obj = db.session.get(meta['model'], obj_id)
    if obj is None:
        abort(404)

    if request.method == 'POST':
        all_units = registry.units(obj)
        for lang in PREFIXED_LANGUAGES:
            values = {
                unit.uid: request.form[_form_name(lang, unit)]
                for unit in all_units
                if _form_name(lang, unit) in request.form
            }
            if values:
                registry.apply_units(obj, lang, values)
        db.session.commit()
        flash('Переклади збережено.', 'success')
        return redirect(url_for('admin.translations_edit', entity=entity, obj_id=obj_id))

    return render_template(
        'admin/translations_edit.html',
        entity=entity,
        entity_label=meta['label'],
        obj=obj,
        obj_name=getattr(obj, meta['name_attr'], None) or f'#{obj_id}',
        fields=_build_fields(obj),
        languages=PREFIXED_LANGUAGES,
        children=_children_sections(entity, obj),
        coverage=registry.coverage_label(obj),
    )
