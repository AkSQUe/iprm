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


# Варіанти апострофа, що трапляються в назвах довідника ("Громадське
# здоров’я") і в старому вільному тексті курсу, набраному з клавіатури
# ("здоров'я"): U+2019 (права одинарна лапка), U+02BC (модифікатор-апостроф)
# і ASCII U+0027. Без зведення до одного символу normalize_name() не бачить
# у них збігу, і бекфіл міграції заводить рядок-дублікат замість того, щоб
# впізнати вже наявний код довідника.
_APOSTROPHE_VARIANTS = ('’', 'ʼ')
_APOSTROPHE_CANONICAL = "'"


def normalize_name(text):
    """Форма для звірки: без крайніх пробілів, стиснуті внутрішні, нижній
    регістр, один варіант апострофа. Такою звіряється старий вільний текст
    курсу з назвами довідника."""
    text = text or ''
    for variant in _APOSTROPHE_VARIANTS:
        text = text.replace(variant, _APOSTROPHE_CANONICAL)
    return ' '.join(text.split()).lower()


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


def names(codes, lang=None):
    """Назви в порядку номенклатури. Невідомий код -- пропуск.

    lang=None -- активна мова запиту (прев'ю адмінки, вибір форми). Знімок
    сертифіката передає мову явно (app.i18n.DEFAULT_LANGUAGE): виданий
    документ не має залежати від локалі того, хто натиснув кнопку видачі.
    """
    known = catalog()
    rows = [known[code] for code in (codes or []) if code in known]
    return [row.t('name', lang=lang) for row in sorted(rows, key=_order_key)]


def line(codes, lang=None):
    """Рядок для сертифіката: назви через кому. Порожньо -- None."""
    return ', '.join(names(codes, lang=lang)) or None


def choices(current=None):
    """{підпис розділу: [(code, назва), ...]} для SelectMultipleField.

    Активні рядки ПЛЮС ті коди, що вже збережені (current), навіть якщо рядок
    деактивований. Інакше WTForms відхилить сабміт із "Not a valid choice", і
    адміністратор не збереже жодної правки старого курсу -- навіть правки
    заголовка, що спеціальностей не стосується.

    Віддає ГОТОВИЙ dict, а не список пар: WTForms 3.2 розпізнає групи
    (<optgroup>) лише в choices-словнику -- список кортежів (підпис, [...])
    воно трактує як плоскі (значення, підпис) і звірка на валідність
    ламається. Виклик лишається `form.bpr_specialty_codes.choices =
    specialties.choices(...)` -- без зайвого `dict(...)` на кожному
    виклику.
    """
    from app.models.specialty import SECTIONS
    keep = set(current or ())
    groups = {}
    for section, label in SECTIONS:
        rows = sorted(
            (row for row in catalog().values()
             if row.section == section and (row.is_active or row.code in keep)),
            key=_order_key,
        )
        if rows:
            groups[label] = [(row.code, row.t('name')) for row in rows]
    return groups


def valid_codes():
    """Усі коди довідника, включно з деактивованими."""
    return set(catalog())


def clean_codes(data):
    """Список кодів без порожніх рядків.

    WTForms відхиляє форгнутий POST із порожнім значенням через
    pre_validate ("Not a valid choice"), але форма -- не єдиний шлях
    запису: цей фільтр -- другий, дешевий захист прямо біля присвоєння
    полю моделі, щоб порожній код ніколи не ліг у bpr_specialty_codes.
    """
    return [code for code in (data or []) if code]


def usage():
    """{code: скільки курсів і проведень його вживають}.

    Адмінці довідника треба вага рядка: позицію з нулем можна видаляти, зайняту
    -- лише деактивувати. JSON-колонку рахуємо в пам'яті: рядків у курсах і
    проведеннях сотні, а SQL-джерела для JSON-масиву в SQLite і Postgres різні.
    """
    from app.extensions import db
    from app.models.course import Course
    from app.models.course_instance import CourseInstance

    counts = {}
    for model in (Course, CourseInstance):
        for (codes,) in db.session.query(model.bpr_specialty_codes).all():
            for code in (codes or []):
                counts[code] = counts.get(code, 0) + 1
    return counts


def legacy_code_for(text, name_to_code, taken=None):
    """Код довідника для старого вільного тексту курсу.

    Повертає (code, missing_name). missing_name не None, коли збігу немає:
    міграція заводить такий рядок деактивованим, щоб значення не загубилось і
    курс не лишився з осиротілим кодом.

    taken -- повний набір уже зайнятих кодів. Якщо не передано, рахується як
    set(name_to_code.values()) -- ЦЕ НЕПОВНИЙ набір: name_to_code індексований
    нормалізованою назвою, а кілька різних кодів довідника нормалізуються до
    однієї й тієї ж назви (регістр/пробіли), тож частина реальних кодів у
    values() губиться і згенерований код може випадково зіткнутися з уже
    наявним (UNIQUE(code)). Викликач із живою базою (міграція) повинен
    передавати taken окремим SELECT code FROM specialties; дефолт лишається
    для викликів без такого контексту (юніт-тести цього модуля).
    """
    name = ' '.join((text or '').split())
    code = name_to_code.get(normalize_name(name))
    if code:
        return code, None
    if taken is None:
        taken = set(name_to_code.values())
    return specialty_code(name, taken=taken), name
