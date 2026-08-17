"""Partner API v1 -- каталог онлайн-курсів для MM Medic.

MM Medic не ходить у Sintegrum і не має власного ключа (рішення Q4 плану):
ІПРМ синхронізує каталог у себе, а сюди віддає вже підготовлені й
опубліковані картки. Отже ключ Sintegrum лишається в одному місці, а зміна
чужого API б'є лише по ІПРМ.

Віддаємо ЛИШЕ опубліковані й не зниклі курси. Курс, знятий з публікації,
просто зникає з видачі -- партнер має позначати такі неактивними у себе,
а не видаляти: на них можуть посилатися його власні записи.
"""
import re
from datetime import datetime, timezone

from flask import jsonify, make_response, request
from sqlalchemy.orm import selectinload

from app.api.v1 import api_v1_bp
from app.api.v1.auth import require_api_key
from app.api.v1.serializers import API_VERSION, serialize_online_course
from app.extensions import csrf, limiter
from app.models.online_course import OnlineCourse

MAX_PER_PAGE = 100
DEFAULT_PER_PAGE = 50
MAX_PAGE = 10_000

# Каталог змінюється рідко (синхронізація раз на годину), тож п'ять хвилин
# кешу партнеру нічого не коштують і знімають зайві запити.
CACHE_TTL_SECONDS = 300


def _parse_pagination():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        return None, None, 'page and per_page must be integers'
    if page < 1 or page > MAX_PAGE:
        return None, None, f'page must be between 1 and {MAX_PAGE}'
    if per_page < 1 or per_page > MAX_PER_PAGE:
        return None, None, f'per_page must be between 1 and {MAX_PER_PAGE}'
    return page, per_page, None


def _parse_updated_since():
    """Інкрементальна синхронізація: ISO-8601 у query-параметрі.

    Пастка: у query-рядку '+' декодується як пробіл, тож коректний
    '2026-08-17T12:00:00+00:00' доїжджає як '...12:00:00 00:00' і
    fromisoformat його не бере. Партнер при цьому не зробив нічого
    поганого, тому відновлюємо зсув, а не віддаємо 400. Наївний
    replace(' ', '+') тут не годиться: пробіл є легальним роздільником
    дати й часу.
    """
    raw = (request.args.get('updated_since') or '').strip()
    if not raw:
        return None, None

    candidates = [raw.replace('Z', '+00:00')]
    restored = re.sub(r' (\d{2}:?\d{2})$', r'+\1', candidates[0])
    if restored != candidates[0]:
        candidates.append(restored)

    for candidate in candidates:
        try:
            value = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value, None

    return None, 'updated_since must be an ISO-8601 datetime'


@api_v1_bp.route('/online-courses', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('60 per minute')
def list_online_courses():
    """Опубліковані онлайн-курси.

    Query params:
      page (int, default 1)
      per_page (int, default 50, max 100)
      updated_since (ISO-8601) -- лише змінені після вказаного моменту
      lang (uk|ru|en) -- мова текстів; за замовчуванням українська
    """
    page, per_page, err = _parse_pagination()
    if err:
        return jsonify({'error': err, 'api_version': API_VERSION}), 400

    updated_since, err = _parse_updated_since()
    if err:
        return jsonify({'error': err, 'api_version': API_VERSION}), 400

    lang = (request.args.get('lang') or '').strip().lower() or None
    if lang and lang not in ('uk', 'ru', 'en'):
        return jsonify({
            'error': "invalid lang; allowed: ['uk', 'ru', 'en']",
            'api_version': API_VERSION,
        }), 400

    # Серіалізатор читає обкладинку й hero кожного курсу, тож без
    # selectinload сторінка на 50 курсів коштувала б понад сотню запитів --
    # і платив би за це кожен прохід синхронізації партнера.
    query = OnlineCourse.query.options(
        selectinload(OnlineCourse.card_media),
        selectinload(OnlineCourse.hero_media),
    ).filter(
        OnlineCourse.is_published.is_(True),
        OnlineCourse.is_vanished.is_(False),
    )
    if updated_since is not None:
        query = query.filter(OnlineCourse.updated_at >= updated_since)

    pagination = query.order_by(
        OnlineCourse.is_featured.desc(),
        OnlineCourse.sort_order,
        OnlineCourse.id,
    ).paginate(page=page, per_page=per_page, error_out=False)

    body = {
        'api_version': API_VERSION,
        'items': [serialize_online_course(item, lang) for item in pagination.items],
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
    }
    response = make_response(jsonify(body))
    response.headers['Cache-Control'] = f'public, max-age={CACHE_TTL_SECONDS}'
    response.headers['Vary'] = 'X-API-Key, Accept-Encoding'
    return response
