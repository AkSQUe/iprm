"""Читання довідника видів заходів БПР.

Довідник крихітний (півтора десятка рядків), а звертань до нього багато:
кожна картка курсу, кожен рядок розкладу, кожен сертифікат. Тому він
читається ЦІЛКОМ одним запитом і кладеться в g на час HTTP-запиту --
інакше сторінка розкладу з десятком проведень дала б десяток запитів.
Той самий підхід, що в app/services/city_glossary.py.

Довідник -- шар назв поверх коду, а не джерело істини про курс. Якщо
таблиці ще немає (код піднявся раніше за міграцію) або БД моргнула, ми
показуємо сирий код і пишемо в лог, але публічну сторінку не кладемо.
"""
import logging

from flask import g, has_app_context

logger = logging.getLogger(__name__)

_CACHE_ATTR = '_event_type_directory'


def reset_cache():
    """Забути закешований довідник. Потрібно після правки рядків в
    адмінці й між тестами: app-контекст у тестах один на всю сесію, тож
    без цього доданий тип не побачила б наступна перевірка."""
    if has_app_context():
        g.pop(_CACHE_ATTR, None)


def directory():
    """{code: EventType} у порядку sort_order -- один запит на запит."""
    if has_app_context() and _CACHE_ATTR in g:
        return g.get(_CACHE_ATTR)

    from app.extensions import db
    from app.models.event_type import EventType
    try:
        rows = EventType.query.order_by(
            EventType.sort_order, EventType.name).all()
        mapping = {row.code: row for row in rows}
    except Exception:
        logger.exception('Event type directory unavailable, falling back to raw codes')
        mapping = {}
        # Без rollback запобіжник шкодить більше, ніж допомагає: на Postgres
        # невдалий запит труїть транзакцію, і наступний запит того ж реквесту
        # гине з InFailedSqlTransaction -- тобто сторінка, яку ми тут
        # рятували, однаково падає, лише з менш зрозумілою помилкою.
        try:
            db.session.rollback()
        except Exception:
            logger.exception('Rollback after event type directory failure failed')

    if has_app_context():
        setattr(g, _CACHE_ATTR, mapping)
    return mapping


def label(code, lang=None):
    """Назва активною (або заданою) мовою. Немає в довіднику -- сам код."""
    if not code:
        return code
    row = directory().get(code)
    return row.t('name', lang) if row is not None else code


def base_name(code):
    """Канонічна (українська, неперекладена) назва -- незалежна від
    активної локалі. Немає в довіднику -- сам код.

    На відміну від label(), джерело для контрактів, які мусять лишатись
    стабільними в будь-якій мовній сесії адміна: xlsx-експорт і drop-down
    тієї самої колонки звіряються саме за цим значенням, а не за
    локалізованою назвою.
    """
    if not code:
        return code
    row = directory().get(code)
    return row.name if row is not None else code


def accusative(code):
    """Знахідний для сертифіката учасника: "завершив(-ла) <accusative>"."""
    return _case(code, 'name_accusative')


def genitive(code):
    """Родовий для лекторського сертифіката: "лектору(-ці) <genitive>"."""
    return _case(code, 'name_genitive')


def _case(code, field):
    """Відмінок із довідника; немає -- називний з малої; немає рядка --
    сам код. Порожній код лишається порожнім: шаблон сертифіката тоді
    друкує запасне "захід"/"заходу"."""
    if not code:
        return code
    row = directory().get(code)
    if row is None:
        return code.lower()
    return getattr(row, field) or row.name.lower()


def choices(current=None):
    """Пари для SelectField: активні типи плюс current, навіть якщо той
    деактивований.

    Без домішування current WTForms відхилив би сабміт старого курсу з
    "Not a valid choice", і адміністратор не зберіг би навіть правку
    заголовка, що типу не стосується.
    """
    rows = directory()
    items = [(code, row.name) for code, row in rows.items() if row.is_active]
    if current and not any(code == current for code, _ in items):
        row = rows.get(current)
        items.append((current, f'{row.name} (застарілий)' if row else current))
    return items


def usage():
    """{code: скільки курсів і проведень цим типом}.

    Адмінці це і вага рядка, і запобіжник: вживаний тип видаляти не можна,
    його деактивують.
    """
    from app.extensions import db
    from app.models.course import Course
    from app.models.course_instance import CourseInstance

    counts = {}
    for model in (Course, CourseInstance):
        rows = (
            db.session.query(model.event_type, db.func.count(model.id))
            .filter(model.event_type.isnot(None), model.event_type != '')
            .group_by(model.event_type)
            .all()
        )
        for code, count in rows:
            counts[code] = counts.get(code, 0) + count
    return counts
