"""Вхідний вебхук Meta Lead Ads: верифікація, підпис, черга.

Тіла запитів і підпис будуються ВИКЛЮЧНО через `tests/support/fake_meta_graph`.
Власний будівник payload-а в тесті означав би другу копію знання про формат
Meta -- і саме та копія лишалась би зеленою, коли реальний формат розійдеться
з нею.

База в тестах спільна на всю сесію (відкат у фікстурі не ізолює commit-и
сервісів), тож кожен тест бере ВЛАСНІ `leadgen_id`, а перевірки рахують
рядки за цими ідентифікаторами, а не по всій таблиці.
"""
import hashlib
import hmac
import re
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models.meta_lead import MetaLeadEvent
from app.models.site_settings import SiteSettings
from app.services import meta_lead_intake
from tests.support.fake_meta_graph import (
    make_webhook_body, make_webhook_value, sign_webhook,
)

URL = '/api/webhooks/meta/leads'
APP_SECRET = 'meta-app-secret-for-tests'
VERIFY_TOKEN = 'meta-verify-token-for-tests'


@pytest.fixture
def meta_settings(app):
    """Налаштування з увімкненою інтеграцією і заданими секретами."""
    site = SiteSettings.get()
    site.meta_leads_enabled = True
    site.meta_app_secret = APP_SECRET
    site.meta_verify_token = VERIFY_TOKEN
    site.meta_page_id = '555000111'
    db.session.commit()
    return site


def _post(client, body, secret=APP_SECRET, header=True):
    raw, signature = sign_webhook(body, secret)
    headers = {'Content-Type': 'application/json'}
    if header:
        headers['X-Hub-Signature-256'] = signature
    return client.post(URL, data=raw, headers=headers)


def _utc(value):
    """SQLite віддає DateTime(timezone=True) БЕЗ tzinfo -- дотягуємо в UTC,
    інакше порівняння зі свіжо-розібраною датою падає TypeError."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _events(*leadgen_ids):
    return MetaLeadEvent.query.filter(
        MetaLeadEvent.leadgen_id.in_([str(i) for i in leadgen_ids])
    ).all()


# --- GET: верифікація підписки -------------------------------------------

def test_verify_returns_challenge_as_plain_text(client, meta_settings):
    resp = client.get(URL, query_string={
        'hub.mode': 'subscribe',
        'hub.verify_token': VERIFY_TOKEN,
        'hub.challenge': '1158201444',
    })

    assert resp.status_code == 200
    # Meta звіряє тіло посимвольно: JSON-обгортка провалила б підписку.
    assert resp.get_data(as_text=True) == '1158201444'
    assert resp.mimetype == 'text/plain'


def test_verify_rejects_wrong_token(client, meta_settings):
    resp = client.get(URL, query_string={
        'hub.mode': 'subscribe',
        'hub.verify_token': 'not-the-token',
        'hub.challenge': '1158201444',
    })

    assert resp.status_code == 403
    assert '1158201444' not in resp.get_data(as_text=True)


def test_verify_rejects_wrong_mode(client, meta_settings):
    resp = client.get(URL, query_string={
        'hub.mode': 'unsubscribe',
        'hub.verify_token': VERIFY_TOKEN,
        'hub.challenge': '1158201444',
    })

    assert resp.status_code == 403


def test_verify_rejects_when_token_not_configured(client, app):
    site = SiteSettings.get()
    site.meta_verify_token = ''
    db.session.commit()

    resp = client.get(URL, query_string={
        'hub.mode': 'subscribe',
        'hub.verify_token': '',
        'hub.challenge': '1158201444',
    })

    # Порожній токен збігається сам із собою -- без окремої перевірки
    # ненастроєний ендпоінт віддавав би challenge будь-кому.
    assert resp.status_code == 403


# --- POST: підпис (критерій приймання N6) --------------------------------

def test_post_without_signature_header_is_rejected(client, meta_settings):
    body = make_webhook_body([make_webhook_value(leadgen_id='7000000000001')])

    resp = _post(client, body, header=False)

    assert resp.status_code == 401
    assert _events('7000000000001') == []


def test_post_with_forged_signature_is_rejected(client, meta_settings):
    body = make_webhook_body([make_webhook_value(leadgen_id='7000000000002')])

    resp = _post(client, body, secret='wrong-secret')

    assert resp.status_code == 401
    assert _events('7000000000002') == []


def test_post_is_rejected_when_app_secret_is_empty(client, app):
    site = SiteSettings.get()
    site.meta_app_secret = ''
    db.session.commit()
    body = make_webhook_body([make_webhook_value(leadgen_id='7000000000003')])

    # Підпис порожнім секретом технічно валідний -- і саме тому ненастроєний
    # App Secret мусить відхиляти, а не звіряти.
    resp = _post(client, body, secret='')

    assert resp.status_code == 401
    assert _events('7000000000003') == []


def test_post_with_tampered_body_is_rejected(client, meta_settings):
    """Підпис рахується по СИРИХ байтах: зміна тіла після підпису ламає його."""
    body = make_webhook_body([make_webhook_value(leadgen_id='7000000000004')])
    raw, signature = sign_webhook(body, APP_SECRET)
    tampered = raw.replace(b'7000000000004', b'7000000000005')

    resp = client.post(URL, data=tampered, headers={
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': signature,
    })

    assert resp.status_code == 401
    assert _events('7000000000004', '7000000000005') == []


# --- POST: постановка в чергу --------------------------------------------

def test_post_queues_pending_event(client, meta_settings):
    value = make_webhook_value(leadgen_id='7000000001001', form_id='9988776655',
                               created_time=1755511452)

    resp = _post(client, make_webhook_body([value]))

    assert resp.status_code == 200
    assert resp.get_data() == b''
    events = _events('7000000001001')
    assert len(events) == 1
    event = events[0]
    assert event.status == MetaLeadEvent.STATUS_PENDING
    assert event.source == MetaLeadEvent.SOURCE_WEBHOOK
    assert event.attempts == 0
    assert event.page_id == '555000111'
    assert event.form_id == '9988776655'
    # Сирий payload зберігається ЦІЛКОМ -- це страховка на випадок помилок
    # у розборі, тож жодного відсіювання полів тут бути не може.
    assert event.raw_payload == value
    # unix-число з вебхука лягло в DateTime(timezone=True).
    assert _utc(event.created_time) == datetime.fromtimestamp(1755511452,
                                                              tz=timezone.utc)


def test_post_updates_last_webhook_at(client, meta_settings):
    site = SiteSettings.get()
    site.meta_last_webhook_at = None
    db.session.commit()

    resp = _post(client, make_webhook_body([
        make_webhook_value(leadgen_id='7000000001002')]))

    assert resp.status_code == 200
    assert SiteSettings.get().meta_last_webhook_at is not None


def test_duplicate_delivery_creates_single_row(client, meta_settings):
    """Критерій приймання N2: повтор доставки не дає другого рядка."""
    body = make_webhook_body([make_webhook_value(leadgen_id='7000000002001')])

    first = _post(client, body)
    second = _post(client, body)

    # Обидва рази 200: 4xx на повтор змусив би Meta ретраїти вже прийняте.
    assert (first.status_code, second.status_code) == (200, 200)
    assert len(_events('7000000002001')) == 1


def test_duplicate_delivery_survives_lost_select_race(app, client, meta_settings,
                                                      monkeypatch):
    """Дві доставки в РІЗНИХ воркерах: обидва SELECT-и порожні.

    Перевірка "спершу SELECT, потім INSERT" тут не рятує -- рятує UNIQUE й
    перехоплений IntegrityError. Підміняємо шов пошуку, щоб відтворити саме
    цей стан у одному процесі.
    """
    value = make_webhook_value(leadgen_id='7000000002002')
    body = make_webhook_body([value])
    assert _post(client, body).status_code == 200

    monkeypatch.setattr(meta_lead_intake, '_find_existing', lambda leadgen_id: None)
    resp = _post(client, body)

    assert resp.status_code == 200
    assert len(_events('7000000002002')) == 1


def test_batch_of_changes_queues_each_lead(client, meta_settings):
    body = make_webhook_body([
        make_webhook_value(leadgen_id='7000000003001'),
        make_webhook_value(leadgen_id='7000000003002'),
        make_webhook_value(leadgen_id='7000000003003'),
    ])

    resp = _post(client, body)

    assert resp.status_code == 200
    assert len(_events('7000000003001', '7000000003002', '7000000003003')) == 3


def test_batch_keeps_new_leads_when_one_is_a_duplicate(client, meta_settings):
    """Дубль усередині пачки не має змивати сусідів.

    Саме тому подія комітиться поштучно: спільний відкат після програного
    гону забрав би з собою вже вставлені рядки того самого тіла.
    """
    assert _post(client, make_webhook_body([
        make_webhook_value(leadgen_id='7000000003101')])).status_code == 200

    resp = _post(client, make_webhook_body([
        make_webhook_value(leadgen_id='7000000003102'),
        make_webhook_value(leadgen_id='7000000003101'),
        make_webhook_value(leadgen_id='7000000003103'),
    ]))

    assert resp.status_code == 200
    assert len(_events('7000000003101', '7000000003102', '7000000003103')) == 3


def test_non_leadgen_change_is_ignored(client, meta_settings):
    body = make_webhook_body([make_webhook_value(leadgen_id='7000000004001')])
    body['entry'][0]['changes'][0]['field'] = 'feed'

    resp = _post(client, body)

    # Сторінка підписана й на інші поля -- чужа подія не помилка.
    assert resp.status_code == 200
    assert _events('7000000004001') == []


def test_foreign_object_is_acknowledged_without_queueing(client, meta_settings):
    body = make_webhook_body([make_webhook_value(leadgen_id='7000000004002')])
    body['object'] = 'instagram'

    resp = _post(client, body)

    assert resp.status_code == 200
    assert _events('7000000004002') == []


def test_malformed_body_is_acknowledged(client, meta_settings):
    raw = b'not json at all'
    signature = 'sha256=' + hmac.new(APP_SECRET.encode(), raw,
                                     hashlib.sha256).hexdigest()

    resp = client.post(URL, data=raw, headers={
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': signature,
    })

    # 200, бо 4xx змусив би Meta ретраїти безнадійний штовх, а після серії
    # невдач -- вимкнути підписку цілком.
    assert resp.status_code == 200


def test_change_without_leadgen_id_is_ignored(client, meta_settings):
    value = make_webhook_value(leadgen_id='7000000004003')
    value.pop('leadgen_id')
    before = MetaLeadEvent.query.count()

    resp = _post(client, make_webhook_body([value]))

    # Без ідентифікатора подія марна -- забирати за нею з Graph API нічого.
    assert resp.status_code == 200
    assert MetaLeadEvent.query.count() == before


# --- POST: жодного походу в Graph API ------------------------------------

def test_post_answers_even_when_graph_api_is_unreachable(client, meta_settings,
                                                         monkeypatch):
    """Доводимо, що ендпоінт у Graph API не ходить ВЗАГАЛІ.

    Три незалежні докази:

    1. будь-який HTTP-запит через `requests` падає -- відповідь усе одно 200;
    2. будь-який метод `MetaGraphClient` падає -- відповідь усе одно 200;
    3. подія лишається `pending` з нулем спроб, тобто її навіть не починали
       обробляти.

    Це не прискіпливість: Meta вважає доставку невдалою, якщо відповідь
    затрималась, а таймаут Graph-клієнта -- 10 секунд на запит.
    """
    import requests

    from app.services import meta_graph_client

    def _explode(*args, **kwargs):
        raise AssertionError('вебхук не має ходити в мережу')

    monkeypatch.setattr(requests, 'request', _explode)
    for name in ('get_lead', 'list_form_leads', 'list_page_forms', 'debug_token',
                 'from_settings'):
        monkeypatch.setattr(meta_graph_client.MetaGraphClient, name, _explode)

    # Пастка мусить бути ЗВЕДЕНА: помилка в підміні зробила б увесь тест
    # порожнім, і він лишався б зеленим навіть із походом у Graph API.
    with pytest.raises(AssertionError):
        requests.request('GET', 'https://graph.facebook.com/v21.0/me')

    resp = _post(client, make_webhook_body([
        make_webhook_value(leadgen_id='7000000005001')]))

    assert resp.status_code == 200
    event = _events('7000000005001')[0]
    assert event.status == MetaLeadEvent.STATUS_PENDING
    assert event.attempts == 0
    assert event.processed_at is None
    assert event.lead_id is None


def test_webhook_module_does_not_import_the_graph_client():
    """Статичний доказ до динамічного: у прийомі немає навіть імпорту.

    Тест на монкіпатчі ловить виклик, але не ловить, наприклад, ліниво
    імпортований клієнт у гілці, куди тест не зайшов.
    """
    import app.api.meta_leads as module

    source = open(module.__file__, encoding='utf-8').read()
    assert 'meta_graph_client' not in source
    assert 'meta_lead_queue' not in source
    assert not re.search(r'^\s*(import|from)\s+requests', source, re.MULTILINE)


# --- інтерфейс для звірки (частина E) ------------------------------------

def test_enqueue_event_accepts_reconcile_source(app, meta_settings):
    """Ту саму функцію кличе звірка -- з іншим джерелом і ISO-датою."""
    event = meta_lead_intake.enqueue_event(
        make_webhook_value(leadgen_id='7000000006001',
                           created_time='2026-08-18T10:14:12+0000'),
        source=MetaLeadEvent.SOURCE_RECONCILE,
    )

    assert event is not None
    assert event.source == MetaLeadEvent.SOURCE_RECONCILE
    # ISO-рядок Graph API зі зсувом без двокрапки розібрано так само, як
    # unix-число з вебхука -- обидві форми йдуть в одну колонку.
    assert _utc(event.created_time) == datetime(2026, 8, 18, 10, 14, 12,
                                                tzinfo=timezone.utc)
    assert event.status == MetaLeadEvent.STATUS_PENDING

    # Той самий лід, уже знайдений вебхуком, звірка не дублює.
    assert meta_lead_intake.enqueue_event(
        make_webhook_value(leadgen_id='7000000006001'),
        source=MetaLeadEvent.SOURCE_RECONCILE) is None


def test_enqueue_event_rejects_unknown_source(app):
    with pytest.raises(ValueError):
        meta_lead_intake.enqueue_event(
            make_webhook_value(leadgen_id='7000000006002'), source='mystery')
