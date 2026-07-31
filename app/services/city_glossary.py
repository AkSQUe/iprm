"""Переклад назв локацій розкладу через довідник City.

CourseInstance.location лишається вільним текстом -- FK і міграції даних не
потрібні. Переклад підбирається звіркою повного нормалізованого рядка:
"Харків" -> запис довідника -> city.t('name'). Немає збігу -- показуємо
оригінал.

Звірка саме за ПОВНИМ рядком, а не за частиною до коми: розбирати
"Харків, вул. Сумська 1" на місто й адресу означало б вгадувати. Якщо в
location пишуть адресу, її додають у довідник цілком.

Канонічна українська лишається у location, тож сортування, JSON-LD, ICS і
партнерське API далі працюють на незмінних даних -- локалізується тільки те,
що читає людина.
"""
import logging

from flask import g, has_app_context

from app.models.city import normalize_city_name as normalize

logger = logging.getLogger(__name__)

_CACHE_ATTR = '_city_glossary'


def _glossary():
    """{нормалізована назва: City} -- один запит на HTTP-запит.

    Довідник крихітний (десятки рядків), тож тягнемо його цілком: інакше
    сторінка розкладу з десятком проведень дала б десяток запитів.
    """
    if has_app_context() and _CACHE_ATTR in g:
        return g.get(_CACHE_ATTR)

    from app.models.city import City
    try:
        mapping = {c.name_normalized: c for c in City.query.all()}
    except Exception:
        # Довідник -- декоративний шар над location. Якщо таблиці ще немає
        # (код піднявся до міграції) або БД моргнула, показуємо оригінальні
        # назви, але НЕ кладемо кожну публічну сторінку.
        logger.exception('City glossary unavailable, falling back to source text')
        mapping = {}

    if has_app_context():
        setattr(g, _CACHE_ATTR, mapping)
    return mapping


def localize_location(text):
    """Назва локації активною мовою; без збігу в довіднику -- як є."""
    if not text:
        return text
    city = _glossary().get(normalize(text))
    return city.t('name') if city is not None else text


def location_usage():
    """{нормалізована локація: {'name': оригінал, 'count': скільки проведень}}.

    Адмінці довідника треба і те, чого бракує, і вага кожного рядка: локація
    з двадцятьма проведеннями важливіша за разову, а рядок довідника з нулем
    проведень -- кандидат на видалення. Рахуємо одним групуючим запитом.

    Різні написання ("київ", " Київ ") зводяться до одного ключа, а лічильники
    складаються -- звірка ж іде за нормалізованою формою.
    """
    from app.extensions import db
    from app.models.course_instance import CourseInstance

    rows = (
        db.session.query(CourseInstance.location, db.func.count(CourseInstance.id))
        .filter(CourseInstance.location.isnot(None),
                CourseInstance.location != '')
        .group_by(CourseInstance.location)
        .all()
    )
    usage = {}
    for location, count in rows:
        entry = usage.setdefault(normalize(location),
                                 {'name': location.strip(), 'count': 0})
        entry['count'] += count
    return usage


def unknown_locations():
    """Локації, що вживаються в розкладі, але відсутні в довіднику.

    Потрібно адмінці: інакше нове місто мовчки лишалось би неперекладеним і
    ніхто б про це не дізнався.
    """
    known = _glossary()
    return sorted(entry['name'] for key, entry in location_usage().items()
                  if key not in known)
