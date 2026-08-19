"""Вхідний вебхук Meta Lead Ads.

Meta шле сюди дві різні речі одним URL:

  * `GET` -- разову верифікацію підписки при збереженні вебхука в
    налаштуваннях застосунку: треба звірити `hub.verify_token` і віддати
    `hub.challenge` ГОЛИМ тілом (`text/plain`). JSON тут не приймається --
    Meta порівнює тіло відповіді з викликом посимвольно;
  * `POST` -- саму подію leadgen. Вона приносить ЛИШЕ ідентифікатори
    (`leadgen_id`, `page_id`, `form_id`), без жодного поля форми: дані
    забирає воркер черги з Graph API.

Через це ендпоінт нічого не розбирає й нікуди не ходить: кладе сиру подію
в чергу, оновлює позначку останнього штовха і відповідає. Meta вважає
доставку невдалою, якщо відповідь затрималась, і починає ретраїти -- а
похід у Graph API з таймаутом 10 с у цьому місці і є той таймаут.
Відповідь мусить бути 200 навіть на тіло, якого ми не зрозуміли: інакше
Meta ретраїтиме безнадійний штовх, а після кількох невдач вимикає
підписку цілком.
"""
import hashlib
import hmac
import logging
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request

from app.extensions import db, limiter
from app.models.meta_lead import MetaLeadEvent
from app.models.site_settings import SiteSettings
from app.services.meta_lead_intake import enqueue_event

logger = logging.getLogger(__name__)

meta_leads_bp = Blueprint('meta_leads', __name__, url_prefix='/api/webhooks/meta')

# Дефолтний ліміт застосунку (200/год за IP) тут не годиться: після
# власного збою Meta віддає накопичені штовхи ПАЧКОЮ з одного діапазону
# адрес, і ліміт відкидав би живі заявки рівно тоді, коли їх найбільше.
# Поріг лишаємо явним, а не знімаємо зовсім -- підпис відсіює чужих, але
# не заважає їм витрачати наш CPU на HMAC.
_RATE_LIMIT = '600 per minute'

_SIGNATURE_HEADER = 'X-Hub-Signature-256'
_SIGNATURE_PREFIX = 'sha256='


def _signature_matches(raw_body, header_value, app_secret):
    """Звірити X-Hub-Signature-256 із HMAC-SHA256 по СИРОМУ тілу.

    `compare_digest`, а не `==`: порівняння рядків завершується на першому
    розбіжному байті, і час відповіді видає, скільки символів підпису
    вгадано.
    """
    if not app_secret or not header_value:
        return False
    if not header_value.startswith(_SIGNATURE_PREFIX):
        return False
    received = header_value[len(_SIGNATURE_PREFIX):].strip().lower()
    if not received:
        return False
    expected = hmac.new(app_secret.encode('utf-8'), raw_body,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(received.encode('ascii', 'ignore'),
                               expected.encode('ascii'))


@meta_leads_bp.route('/leads', methods=['GET'])
@limiter.limit(_RATE_LIMIT)
def verify_subscription():
    """Верифікація підписки: `hub.challenge` у відповідь на вірний токен."""
    site = SiteSettings.get()
    expected = (site.meta_verify_token or '').strip()

    mode = request.args.get('hub.mode', '')
    token = request.args.get('hub.verify_token', '')
    challenge = request.args.get('hub.challenge', '')

    if mode != 'subscribe' or not expected or not hmac.compare_digest(
            token.encode('utf-8'), expected.encode('utf-8')):
        # Токен -- теж секрет: успішна відповідь сторонньому підтвердила б,
        # що інтеграція існує. Тому текст відмови однаковий для всіх причин.
        logger.warning('Meta webhook verification rejected (mode=%r)', mode)
        return Response('forbidden', status=403, mimetype='text/plain')

    logger.info('Meta webhook verification passed')
    return Response(challenge, status=200, mimetype='text/plain')


@meta_leads_bp.route('/leads', methods=['POST'])
@limiter.limit(_RATE_LIMIT)
def receive_leadgen():
    """Прийняти подію leadgen і покласти її в чергу."""
    # СПЕРШУ сирі байти, і лише потім будь-який парсинг. `get_json()`
    # раніше цього рядка ламає перевірку підпису на першому ж нюансі
    # кодування: HMAC рахується по тому, що надіслала Meta, а не по тому,
    # що ми змогли з нього відтворити.
    raw = request.get_data()

    site = SiteSettings.get()
    secret = (site.meta_app_secret or '').strip()
    if not _signature_matches(raw, request.headers.get(_SIGNATURE_HEADER, ''), secret):
        # Тіло НЕ розбирається: непідписаний запит не заслуговує ні на
        # рядок у черзі, ні на витрачений на нього JSON-парсер.
        logger.warning('Meta webhook rejected: invalid signature (%s bytes)', len(raw))
        return jsonify({'status': 'invalid_signature'}), 401

    payload = request.get_json(force=True, silent=True)

    seen = 0
    queued = 0
    if isinstance(payload, dict) and payload.get('object') == 'page':
        for entry in payload.get('entry') or []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get('changes') or []:
                if not isinstance(change, dict) or change.get('field') != 'leadgen':
                    # Сторінка може бути підписана й на інші поля (feed,
                    # messages). Чужа подія -- не помилка, її просто не наша
                    # справа розбирати.
                    continue
                seen += 1
                if enqueue_event(change.get('value'),
                                 source=MetaLeadEvent.SOURCE_WEBHOOK) is not None:
                    queued += 1
    else:
        logger.info('Meta webhook ignored: object=%r',
                    payload.get('object') if isinstance(payload, dict) else None)

    # Позначку часу ставимо на БУДЬ-ЯКИЙ підписаний штовх, навіть на той,
    # якого не зрозуміли: моніторинг тиші питає "чи жива доставка", а не
    # "чи були ліди". Інакше зміна формату виглядала б як мертвий вебхук.
    #
    # ПІСЛЯ циклу, а не до нього: `enqueue_event` при програному гоні за
    # UNIQUE робить rollback, і виставлена раніше позначка зникла б разом
    # із його вставкою -- мовчки, бо відповідь усе одно 200.
    site.meta_last_webhook_at = datetime.now(timezone.utc)
    db.session.commit()

    logger.info('Meta webhook accepted: %s leadgen change(s), %s queued', seen, queued)
    # Порожнє тіло і 200 негайно. Жодного походу в Graph API -- лід забере
    # воркер черги.
    return '', 200
