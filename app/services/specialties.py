"""Довідник спеціальностей для рядка «Спеціальності:» на сертифікаті.

Номенклатура (Додаток 1 до Порядку проведення атестації працівників сфери
охорони здоров'я) живе таблицею specialties: вона змінюється наказами МОЗ,
тож актуалізація -- робота адміністратора на /admin/specialties, а не
деплой.

Курс і проведення посилаються на рядки довідника КОДАМИ, а не FK на id:
код стабільний, читається в логах і переживає перезаливку довідника.
"""
import logging

from flask import g, has_app_context

from app.services.blog_service import slugify

logger = logging.getLogger(__name__)

# Ширина колонки specialties.code.
CODE_MAX_LENGTH = 60

_CACHE_ATTR = '_specialties_catalog'


def normalize_name(text):
    """Форма для звірки: без крайніх пробілів, стиснуті внутрішні, нижній
    регістр. Такою звіряється старий вільний текст курсу з назвами
    довідника."""
    return ' '.join((text or '').split()).lower()


def specialty_code(name, taken=()):
    """Код рядка довідника з української назви -- латинський slug.

    taken -- уже зайняті коди; при збігу додається -2, -3 ... Збіги реальні:
    "Бактеріологія" стоїть і серед лікарських спеціальностей, і серед
    спеціальностей професіоналів.

    Потрібно і парсеру номенклатури, і бекфілу міграції, тому живе тут, а не
    всередині інструмента.
    """
    base = slugify(name)[:CODE_MAX_LENGTH].strip('-') or 'specialty'
    code, n = base, 2
    while code in taken:
        suffix = f'-{n}'
        code = base[:CODE_MAX_LENGTH - len(suffix)].strip('-') + suffix
        n += 1
    return code


def catalog():
    """{code: Specialty} -- один запит на HTTP-запит.

    Довідник читається цілком: він на дві сотні коротких рядків, а сторінка
    зі списком проведень інакше дала б запит на кожне проведення.
    """
    if has_app_context() and _CACHE_ATTR in g:
        return g.get(_CACHE_ATTR)

    from app.models.specialty import Specialty
    try:
        rows = Specialty.query.all()
        mapping = {row.code: row for row in rows}
    except Exception:
        # Довідник -- шар над збереженими кодами. Якщо таблиці ще немає (код
        # піднявся до міграції) або БД моргнула, сертифікат друкується без
        # рядка спеціальностей, але сторінка не падає.
        logger.exception('Specialties catalog unavailable')
        mapping = {}

    if has_app_context():
        setattr(g, _CACHE_ATTR, mapping)
    return mapping


def _order_key(row):
    from app.models.specialty import SECTIONS
    sections = [code for code, _label in SECTIONS]
    position = sections.index(row.section) if row.section in sections else len(sections)
    return (position, row.sort_order, row.name)


def names(codes):
    """Назви активною мовою в порядку номенклатури. Невідомий код -- пропуск."""
    known = catalog()
    rows = [known[code] for code in (codes or []) if code in known]
    return [row.t('name') for row in sorted(rows, key=_order_key)]


def line(codes):
    """Рядок для сертифіката: назви через кому. Порожньо -- None."""
    return ', '.join(names(codes)) or None


def choices(current=None):
    """[(підпис розділу, [(code, назва), ...])] для SelectMultipleField.

    Активні рядки ПЛЮС ті коди, що вже збережені (current), навіть якщо рядок
    деактивований. Інакше WTForms відхилить сабміт із "Not a valid choice", і
    адміністратор не збереже жодної правки старого курсу -- навіть правки
    заголовка, що спеціальностей не стосується.
    """
    from app.models.specialty import SECTIONS
    keep = set(current or ())
    groups = []
    for section, label in SECTIONS:
        rows = sorted(
            (row for row in catalog().values()
             if row.section == section and (row.is_active or row.code in keep)),
            key=_order_key,
        )
        if rows:
            groups.append((label, [(row.code, row.t('name')) for row in rows]))
    return groups


def valid_codes():
    """Усі коди довідника, включно з деактивованими."""
    return set(catalog())
