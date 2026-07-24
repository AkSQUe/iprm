"""Адмін-редактор перекладів контенту БД (ru/en).

Універсальна сторінка /admin/translations/<entity>/<id>: для кожного поля
з __translatable__ моделі показує український оригінал (read-only) і поля
вводу для ru/en. Збереження -- через TranslatableMixin.set_translation
(порожнє значення видаляє переклад -> фолбек на укр).

JSON-поля (faq, регалії, блоки блогу, items) редагуються як JSON-текст
зі збереженням структури оригіналу -- це свідомий KISS-компроміс
(структурні редактори перекладів -- окрема задача поза Фазою 4).
"""
import json

from flask import abort, flash, redirect, render_template, request, url_for

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.i18n import PREFIXED_LANGUAGES

# Людські назви полів для форми (інакше -- сира назва колонки).
FIELD_LABELS = {
    'title': 'Назва', 'subtitle': 'Підзаголовок', 'description': 'Опис',
    'short_description': 'Короткий опис', 'target_audience': 'Цільова аудиторія',
    'tags': 'Теги', 'speaker_info': 'Про спікера', 'agenda': 'Програма (agenda)',
    'faq': 'FAQ', 'roi_hint': 'ROI-підказка', 'bpr_specialties': 'Спеціальності БПР',
    'full_name': 'ПІБ', 'full_name_dative': 'ПІБ (давальний)', 'role': 'Роль',
    'bio': 'Біографія', 'certificates': 'Сертифікати', 'patents': 'Патенти',
    'articles': 'Статті', 'research': 'Дослідження', 'skills': 'Навички',
    'education': 'Освіта', 'additional_education': 'Додаткова освіта',
    'work_experience': 'Досвід роботи', 'excerpt': 'Анонс',
    'content': 'Контент (блоки)', 'meta_title': 'Meta title',
    'meta_description': 'Meta description', 'name': 'Назва',
    'heading': 'Заголовок', 'items': 'Пункти', 'author_name': 'Автор',
    'author_role': 'Роль автора', 'city': 'Місто', 'text': 'Текст',
    'company_name': 'Назва компанії', 'company_full_name': 'Повна назва',
    'address': 'Адреса', 'business_hours': 'Години роботи',
}


def _registry():
    """entity-ключ -> модель + метадані для breadcrumb/заголовка."""
    from app.models.blog_post import BlogPost
    from app.models.clinic import Clinic
    from app.models.course import Course
    from app.models.course_tariff import CourseTariff
    from app.models.instance_tariff import InstanceTariff
    from app.models.program_block import ProgramBlock
    from app.models.review import Review
    from app.models.site_settings import SiteSettings
    from app.models.trainer import Trainer
    return {
        'course': {'model': Course, 'label': 'Курс', 'name_attr': 'title'},
        'trainer': {'model': Trainer, 'label': 'Тренер', 'name_attr': 'full_name'},
        'blog_post': {'model': BlogPost, 'label': 'Допис блогу', 'name_attr': 'title'},
        'clinic': {'model': Clinic, 'label': 'Клініка', 'name_attr': 'name'},
        'course_tariff': {'model': CourseTariff, 'label': 'Тариф курсу', 'name_attr': 'name'},
        'instance_tariff': {'model': InstanceTariff, 'label': 'Тариф проведення', 'name_attr': 'name'},
        'program_block': {'model': ProgramBlock, 'label': 'Блок програми', 'name_attr': 'heading'},
        'review': {'model': Review, 'label': 'Відгук', 'name_attr': 'author_name'},
        'site_settings': {'model': SiteSettings, 'label': 'Налаштування сайту', 'name_attr': 'company_name'},
    }


def _widget_for(model, field):
    """text | textarea | json -- за типом колонки моделі."""
    column = model.__table__.columns.get(field)
    if column is None:
        return 'textarea'
    type_name = type(column.type).__name__.upper()
    if 'JSON' in type_name:
        return 'json'
    if type_name == 'TEXT':
        return 'textarea'
    return 'text'


def _build_fields(obj):
    """Метадані полів для шаблону: оригінал + поточні переклади."""
    model = type(obj)
    translations = obj.translations or {}
    fields = []
    for field in obj.__translatable__:
        widget = _widget_for(model, field)
        uk_value = getattr(obj, field)
        if widget == 'json':
            uk_display = json.dumps(uk_value or [], ensure_ascii=False, indent=2)
        else:
            uk_display = uk_value or ''
        values = {}
        for lang in PREFIXED_LANGUAGES:
            value = (translations.get(lang) or {}).get(field)
            if widget == 'json':
                values[lang] = (
                    json.dumps(value, ensure_ascii=False, indent=2) if value else ''
                )
            else:
                values[lang] = value or ''
        fields.append({
            'name': field,
            'label': FIELD_LABELS.get(field, field),
            'widget': widget,
            'uk': uk_display,
            'values': values,
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
                 'done': _coverage(b)}
                for b in sorted(obj.program_blocks, key=lambda b: b.sort_order or 0)
            ],
        },
        {
            'title': 'Тарифи курсу (шаблони)',
            'items': [
                {'entity': 'course_tariff', 'id': t.id, 'name': t.name,
                 'done': _coverage(t)}
                for t in obj.default_tariffs
            ],
        },
    ]


def _coverage(obj):
    """'ru 3/5, en 0/5' -- скільки полів перекладено."""
    translations = obj.translations or {}
    total = len(obj.__translatable__)
    parts = []
    for lang in PREFIXED_LANGUAGES:
        done = sum(
            1 for f in obj.__translatable__
            if (translations.get(lang) or {}).get(f) not in (None, '', [], {})
        )
        parts.append(f'{lang} {done}/{total}')
    return ', '.join(parts)


@admin_bp.route('/translations/<entity>/<int:obj_id>', methods=['GET', 'POST'])
@admin_required
def translations_edit(entity, obj_id):
    registry = _registry()
    meta = registry.get(entity)
    if meta is None:
        abort(404)
    obj = db.session.get(meta['model'], obj_id)
    if obj is None:
        abort(404)

    if request.method == 'POST':
        errors = []
        for field in obj.__translatable__:
            widget = _widget_for(meta['model'], field)
            for lang in PREFIXED_LANGUAGES:
                key = f'{lang}__{field}'
                if key not in request.form:
                    continue
                raw = request.form.get(key, '').strip()
                if widget == 'json':
                    if raw:
                        try:
                            value = json.loads(raw)
                        except ValueError:
                            errors.append(
                                f'{FIELD_LABELS.get(field, field)} ({lang}): некоректний JSON'
                            )
                            continue
                    else:
                        value = None
                else:
                    value = raw or None
                obj.set_translation(lang, field, value)
        if errors:
            db.session.rollback()
            for err in errors:
                flash(err, 'error')
        else:
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
        coverage=_coverage(obj),
    )
