"""Partner API v1 — довідник медичних спеціалізацій.

Партнер (MM Medic) сегментує розсилки за спеціалізацією: «усім ортопедам»,
«косметологам, які не були на курсі». Коди спеціалізацій приходять до нього
в кожній картці учасника (`/participants`), але БЕЗ підписів — а показувати
менеджеру `orthopedics_traumatology` замість «Травматологія та ортопедія»
не можна.

**Чому окремий роут, а не разове перенесення списку.** Перелік лишається за
нами: він росте разом із номенклатурою МОЗ і з нашими курсами. Скопійований
одного разу, він розійшовся б із нашим за місяці, і кожен новий код партнеру
довелося б заводити руками — тобто помічати його вручну.

Список — константа в коді (`app/models/specializations.py`), не таблиця; цей
роут просто віддає його назовні. Публічних даних тут немає, але ключ усе одно
потрібен: він же обмежує частоту й дає нам знати, хто саме читає.
"""
from flask import jsonify, make_response

from app.api.v1 import api_v1_bp
from app.api.v1.auth import require_api_key
from app.api.v1.serializers import API_VERSION
from app.extensions import csrf, limiter
from app.models.specializations import SPECIALIZATIONS


@api_v1_bp.route('/specializations', methods=['GET'])
@csrf.exempt
@require_api_key
@limiter.limit('60 per minute')
def list_specializations():
    """Коди та підписи спеціалізацій.

    Підписи віддаються українською — базовою мовою довідника. Локалізація на
    льоту (`localized_specializations`) тут навмисно НЕ застосовується:
    партнер зберігає довідник у себе один раз, а мову вибирає при показі, і
    відповідь, що змінюється залежно від заголовка запиту, зробила б його
    копію недетермінованою.
    """
    items = [{'code': code, 'title': title} for code, title in SPECIALIZATIONS]

    response = make_response(jsonify({
        'api_version': API_VERSION,
        'items': items,
        'total': len(items),
    }))
    # Довідник змінюється рідко: годину кешу партнер може тримати спокійно,
    # а от «назавжди» зробило б новий код невидимим до перезапуску.
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response
