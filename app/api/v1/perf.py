"""Приймання замірів швидкості від tools/perf/perf_check.py --push.

Єдиний ендпоінт: POST /api/v1/perf/runs. Автентифікація -- X-API-Key з
SiteSettings.perf_api_key (ротація на /admin/perf). Перегляд прийнятого --
адмінка, /admin/perf.
"""
import logging

from flask import jsonify, request, url_for

from app.api.v1 import api_v1_bp
from app.api.v1.auth import require_perf_key
from app.extensions import csrf, limiter
from app.services.perf_service import PerfIngestError, ingest_run

logger = logging.getLogger(__name__)

# Прогін триває хвилини, тож навіть кілька машин не наблизяться до стелі --
# ліміт тут лише як захист від зациклених клієнтів.
RATE_LIMIT = '30 per hour'


@api_v1_bp.route('/perf/runs', methods=['POST'])
@csrf.exempt
@require_perf_key
@limiter.limit(RATE_LIMIT)
def perf_run_create():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({'error': 'Очікується JSON-тіло запиту'}), 400

    try:
        run = ingest_run(payload)
    except PerfIngestError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception:
        logger.exception('perf: не вдалося зберегти прогін')
        return jsonify({'error': 'Не вдалося зберегти прогін'}), 500

    return jsonify({
        'id': run.id,
        'verdict': run.verdict,
        'pages_total': run.pages_total,
        'pages_warn': run.pages_warn,
        'pages_fail': run.pages_fail,
        'admin_url': url_for('admin.perf_run_detail', run_id=run.id, _external=True),
    }), 201
