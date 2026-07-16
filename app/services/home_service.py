"""Збір контексту публічної Головної сторінки.

Виносить усю логіку даних із main.index у сервіс (тонший route, SRP).
Живі дані (курси, місця, дати) щоразу свіжі; сайт-широка статистика
кешується коротким TTL (той самий in-process патерн, що й каталог MM Medic).
"""
import time

from app.services import course_listing

# Кеш статистики "Інститут у цифрах": цифри змінюються рідко, тож короткий
# TTL знімає count-запити з найвідвідуванішої сторінки. In-process (per-worker).
_STATS_TTL = 300  # секунд
_stats_cache = {'data': None, 'ts': 0.0}


def invalidate_stats_cache():
    """Скинути кеш статистики (напр. після масових змін у каталозі/тренерах)."""
    _stats_cache['data'] = None
    _stats_cache['ts'] = 0.0


def _home_stats(courses, upcoming_by_course):
    now = time.time()
    if (_stats_cache['data'] is not None
            and (now - _stats_cache['ts']) < _STATS_TTL):
        return _stats_cache['data']

    from datetime import datetime, timezone
    from app.models.trainer import Trainer
    from app.models.site_settings import SiteSettings

    founding_year = SiteSettings.get().founding_year or 2015
    data = {
        'years': max(0, datetime.now(timezone.utc).year - founding_year),
        'courses': len(courses),
        'trainers': Trainer.query.filter_by(is_active=True).count(),
        'directions': len({tag for c in courses for tag in (c.tags or [])}),
        'upcoming': sum(len(v) for v in upcoming_by_course.values()),
    }
    _stats_cache['data'] = data
    _stats_cache['ts'] = now
    return data


def home_context():
    """Повний контекст рендеру Головної (dict для render_template(**...))."""
    from app.models.trainer import Trainer
    from app.models.clinic import Clinic
    from app.models.review import Review
    from app.utils import ensure_utc

    courses, upcoming_by_course, capacity, open_ids = (
        course_listing.gather_active_courses(featured_first=True)
    )

    # Найближчі проведення (плоский список) -- блок "Календар".
    home_upcoming = sorted(
        [i for c in courses for i in upcoming_by_course[c.id] if i.start_date],
        key=lambda i: ensure_utc(i.start_date),
    )[:6]

    # Курси з ціною для селектора ROI-калькулятора (slug -> преселект deep-link).
    roi_courses = []
    for c in courses:
        insts = upcoming_by_course.get(c.id, [])
        prices = [i.effective_price for i in insts if i.effective_price]
        price = min(prices) if prices else (c.base_price or 0)
        if price and price > 0:
            roi_courses.append({'title': c.title, 'price': int(price), 'slug': c.slug})

    # Один запит тренерів: перші 6 -- показ, len -- для лічильника.
    all_trainers = Trainer.query.filter_by(is_active=True).order_by(
        Trainer.full_name,
    ).all()
    clinics = Clinic.query.filter_by(is_active=True).order_by(
        Clinic.sort_order,
    ).limit(4).all()

    return {
        'featured_courses': courses[:6],
        'upcoming_by_course': upcoming_by_course,
        'seats_left_map': capacity,
        'open_instance_ids': open_ids,
        'home_upcoming': home_upcoming,
        'roi_courses': roi_courses,
        'trainers': all_trainers[:6],
        'clinics': clinics,
        'reviews': Review.published(),
        'home_stats': _home_stats(courses, upcoming_by_course),
    }
