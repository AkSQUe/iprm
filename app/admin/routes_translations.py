"""Адмін-редактор перекладів контенту БД (ru/en).

Універсальна сторінка /admin/translations/<entity>/<id>: для кожного поля
з __translatable__ моделі показує український оригінал (read-only) і поля
вводу для ru/en. Збереження -- через TranslatableMixin.set_translation
(порожнє значення видаляє переклад -> фолбек на укр).

JSON-поля (faq, регалії, блоки блогу, items) редагуються "поле-проти-поля":
структура розбирається на текстові фрагменти (_walk_leaves), технічні ключі
(TECHNICAL_KEYS) і розмітка недоторкані; при збереженні повна структура
збирається з канонічної укр-версії з підстановкою перекладених фрагментів.
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


# Ключі JSON-структур, які НЕ перекладаються (технічні/медіа/навігаційні).
TECHNICAL_KEYS = {
    'type', 'id', 'url', 'src', 'href', 'slug', 'youtube_id', 'video_id',
    'media_id', 'image', 'icon', 'anchor', 'level', 'align', 'alignment',
    'style', 'format', 'code', 'variant', 'target', 'rel', 'lang',
}


def _has_letters(value):
    return any(ch.isalpha() for ch in value)


def _walk_leaves(value, path=''):
    """Текстові фрагменти JSON-структури: [(шлях 'a.0.b', укр-значення)].
    Перекладаються лише str-значення з літерами поза TECHNICAL_KEYS;
    структура (dict/list) і технічні значення недоторкані."""
    leaves = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f'{path}{key}'
            if isinstance(item, (dict, list)):
                leaves += _walk_leaves(item, child + '.')
            elif isinstance(item, str) and key not in TECHNICAL_KEYS and _has_letters(item):
                leaves.append((child, item))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            child = f'{path}{i}'
            if isinstance(item, (dict, list)):
                leaves += _walk_leaves(item, child + '.')
            elif isinstance(item, str) and _has_letters(item):
                leaves.append((child, item))
    return leaves


def _get_at(value, path):
    try:
        for token in path.split('.'):
            value = value[int(token)] if isinstance(value, list) else value[token]
        return value
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _set_at(value, path, new):
    tokens = path.split('.')
    for token in tokens[:-1]:
        value = value[int(token)] if isinstance(value, list) else value[token]
    last = tokens[-1]
    if isinstance(value, list):
        value[int(last)] = new
    else:
        value[last] = new


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
            # Поле-проти-поля: кожен текстовий фрагмент структури -- окремий
            # рядок перекладу; JSON руками не редагується.
            leaves = []
            for path, uk_leaf in _walk_leaves(uk_value or []):
                leaf_values = {}
                for lang in PREFIXED_LANGUAGES:
                    stored = (translations.get(lang) or {}).get(field)
                    value = _get_at(stored, path) if stored else None
                    # Збережена структура містить укр-текст для неперекладених
                    # фрагментів -- у формі показуємо лише реальні переклади.
                    leaf_values[lang] = value if (
                        isinstance(value, str) and value != uk_leaf
                    ) else ''
                leaves.append({
                    'path': path,
                    'uk': uk_leaf,
                    'trans': leaf_values,
                    'rows': min(8, max(2, len(uk_leaf) // 70 + 1)),
                })
            fields.append({
                'name': field,
                'label': FIELD_LABELS.get(field, field),
                'widget': 'json',
                'leaves': leaves,
            })
            continue
        values = {
            lang: (translations.get(lang) or {}).get(field) or ''
            for lang in PREFIXED_LANGUAGES
        }
        fields.append({
            'name': field,
            'label': FIELD_LABELS.get(field, field),
            'widget': widget,
            'uk': uk_value or '',
            'trans': values,
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


def apply_inline_translations(obj, form=None):
    """Зберегти переклади з інлайн-вкладок адмін-форм (course_edit,
    trainer_edit, blog_edit): інпути tr__<lang>__<поле>. Викликається в
    POST-обробниках ПІСЛЯ створення/наповнення obj, до commit (commit --
    на caller-ові). Відсутні у формі ключі не чіпаються, тож форми з
    частковим набором полів безпечні. Повертає список помилок JSON-полів.
    """
    form = form if form is not None else request.form
    errors = []
    for field in obj.__translatable__:
        widget = _widget_for(type(obj), field)
        for lang in PREFIXED_LANGUAGES:
            key = f'tr__{lang}__{field}'
            if key not in form:
                continue
            raw = (form.get(key) or '').strip()
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
    return errors


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
        import copy as _copy
        for field in obj.__translatable__:
            widget = _widget_for(meta['model'], field)
            if widget == 'json':
                # Зібрати повну структуру з канонічної укр-версії, підставивши
                # перекладені фрагменти. Жодного перекладу -> None (фолбек).
                uk_value = getattr(obj, field)
                leaves = _walk_leaves(uk_value or [])
                for lang in PREFIXED_LANGUAGES:
                    if not any(
                        f'{lang}__{field}__{path}' in request.form
                        for path, _uk in leaves
                    ):
                        continue
                    translated = _copy.deepcopy(uk_value)
                    any_translated = False
                    for path, _uk in leaves:
                        raw = request.form.get(f'{lang}__{field}__{path}', '').strip()
                        if raw:
                            _set_at(translated, path, raw)
                            any_translated = True
                    obj.set_translation(
                        lang, field, translated if any_translated else None
                    )
                continue
            for lang in PREFIXED_LANGUAGES:
                key = f'{lang}__{field}'
                if key not in request.form:
                    continue
                obj.set_translation(lang, field, request.form.get(key, '').strip() or None)
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
