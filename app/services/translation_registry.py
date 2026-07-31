"""Реєстр перекладних одиниць: єдине джерело правди про те, ЩО саме
перекладається в сутності.

Споживачі -- адмін-редактор /admin/translations, інлайн мовні вкладки в
формах і (далі) xlsx-канал експорту/імпорту перекладів. Без цього модуля
кожен із них мав би власне уявлення про перелік полів і про розбір
JSON-структур, і вони б розійшлися.

Одиниця перекладу (TranslationUnit) -- найдрібніше, що перекладач бачить
окремим рядком: або ціле скалярне поле (Назва, Опис), або один текстовий
листок JSON-структури (одне питання FAQ, один пункт програми).

Ідентифікатор одиниці -- `uid`:
    'title'                -- скалярне поле
    'faq:9c1f2a3b4d5e'     -- листок JSON-поля (хеш українського джерела)
uid стабільний між експортом і імпортом, і не залежить від позиції листка
в структурі.
"""
from dataclasses import dataclass

from app.i18n import PREFIXED_LANGUAGES, source_key, walk_leaves

# Людські назви полів для форм і xlsx (інакше -- сира назва колонки).
FIELD_LABELS = {
    'title': 'Назва', 'subtitle': 'Підзаголовок', 'description': 'Опис',
    'short_description': 'Короткий опис', 'target_audience': 'Цільова аудиторія',
    'tags': 'Теги', 'speaker_info': 'Про спікера', 'agenda': 'Програма (agenda)',
    'faq': 'FAQ', 'roi_hint': 'ROI-підказка', 'bpr_specialties': 'Спеціальності БПР',
    'final_cta_text': 'Фінальний заклик',
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


def entity_registry():
    """entity-ключ -> модель + метадані для breadcrumb/заголовка."""
    from app.models.blog_post import BlogPost
    from app.models.city import City
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
        'city': {'model': City, 'label': 'Локація', 'name_attr': 'name'},
        'site_settings': {'model': SiteSettings, 'label': 'Налаштування сайту', 'name_attr': 'company_name'},
    }


def field_label(field):
    return FIELD_LABELS.get(field, field)


def widget_for(model, field):
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


@dataclass(frozen=True)
class TranslationUnit:
    """Один перекладний фрагмент сутності."""
    field: str            # назва колонки ('title', 'faq')
    label: str            # людська назва поля ('Назва', 'FAQ')
    widget: str           # 'text' | 'textarea' | 'json'
    source: str           # український оригінал
    src_key: str | None   # хеш джерела для JSON-листка; None для скаляра
    path: str | None      # шлях листка в структурі -- лише для довідки

    @property
    def uid(self):
        return self.field if self.src_key is None else f'{self.field}:{self.src_key}'

    @property
    def is_json_leaf(self):
        return self.src_key is not None


def units(obj):
    """Перекладні одиниці сутності, у порядку оголошення __translatable__.

    JSON-листки з однаковим українським джерелом схлопуються в одну одиницю:
    вони й зберігаються під одним ключем, тож перекладаються разом.
    """
    model = type(obj)
    result = []
    for field in obj.__translatable__:
        widget = widget_for(model, field)
        value = getattr(obj, field)
        if widget != 'json':
            result.append(TranslationUnit(
                field=field, label=field_label(field), widget=widget,
                source=value or '', src_key=None, path=None,
            ))
            continue
        seen = set()
        for path, uk_leaf in walk_leaves(value or []):
            key = source_key(uk_leaf)
            if key in seen:
                continue
            seen.add(key)
            result.append(TranslationUnit(
                field=field, label=field_label(field), widget='json',
                source=uk_leaf, src_key=key, path=path,
            ))
    return result


def stored_value(obj, lang, unit):
    """Поточний збережений переклад одиниці ('' якщо немає)."""
    bucket = (obj.translations or {}).get(lang) or {}
    if not unit.is_json_leaf:
        return bucket.get(unit.field) or ''
    overrides = bucket.get(unit.field)
    if not isinstance(overrides, dict):
        return ''
    return overrides.get(unit.src_key) or ''


def apply_units(obj, lang, values):
    """Записати переклади з мапи {uid: текст}.

    Поле вважається "під керуванням" виклику, якщо в `values` є хоч один його
    uid; тоді для JSON-полів мапа оверрайдів перезбирається повністю (це
    єдиний спосіб дати можливість стерти останній переклад). Поля, чиїх uid у
    `values` немає, не чіпаються -- тож форми з частковим набором полів
    безпечні.
    """
    by_field = {}
    for unit in units(obj):
        if unit.uid in values:
            by_field.setdefault(unit.field, []).append(unit)

    for field, field_units in by_field.items():
        first = field_units[0]
        if not first.is_json_leaf:
            obj.set_translation(lang, field, (values[first.uid] or '').strip() or None)
            continue
        overrides = {}
        for unit in field_units:
            text = (values[unit.uid] or '').strip()
            # Переклад, що дослівно дорівнює оригіналу, не зберігаємо --
            # фолбек на укр дасть той самий результат без зайвих даних.
            if text and text != unit.source.strip():
                overrides[unit.src_key] = text
        obj.set_translation(lang, field, overrides or None)


def field_units(obj, field):
    """Одиниці одного поля (для JSON -- усі його текстові фрагменти)."""
    return [u for u in units(obj) if u.field == field]


def field_status(obj, field):
    """{'ru': (перекладено, всього), 'en': (...)} по одному полю.

    Живить індикатор біля поля в адмін-формах: без нього не видно, чи
    переклад узагалі є, поки не перемкнеш вкладку.
    """
    field_us = field_units(obj, field)
    total = len(field_us)
    return {
        lang: (sum(1 for u in field_us if stored_value(obj, lang, u)), total)
        for lang in PREFIXED_LANGUAGES
    }


def inline_leaves(obj, field):
    """Дані для інлайн-панелей перекладу JSON-поля в адмін-формі.

    Повертає [{suffix, source, rows, values}]; suffix іде в ім'я інпута
    (`tr__<lang>__<suffix>`) і містить хеш джерела, тож редагування
    українського тексту в тій самій формі не збиває прив'язку.
    """
    return [
        {
            'suffix': f'{u.field}__{u.src_key}',
            'source': u.source,
            'rows': min(6, max(2, len(u.source) // 80 + 1)),
            'values': {
                lang: stored_value(obj, lang, u) for lang in PREFIXED_LANGUAGES
            },
        }
        for u in field_units(obj, field) if u.is_json_leaf
    ]


def coverage(obj):
    """{'ru': (перекладено, всього), 'en': (...)} -- рахунок по ОДИНИЦЯХ.

    Саме по одиницях, а не по полях: інакше FAQ з одним перекладеним
    питанням із шістнадцяти рахувався б виконаним полем.
    """
    all_units = units(obj)
    total = len(all_units)
    return {
        lang: (
            sum(1 for u in all_units if stored_value(obj, lang, u)),
            total,
        )
        for lang in PREFIXED_LANGUAGES
    }


def coverage_label(obj):
    """'ru 3/58, en 0/58' -- короткий підпис покриття для списків."""
    return ', '.join(
        f'{lang} {done}/{total}'
        for lang, (done, total) in coverage(obj).items()
    )
