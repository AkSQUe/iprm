"""Клієнт Meta Graph API для приймання лідів з Lead Ads.

Вебхук Meta приносить лише ідентифікатори (`leadgen_id`, `form_id`,
`page_id`) -- самі відповіді форми доводиться забирати окремим запитом.
Цей модуль і є тим походом до Meta: дістати лід, перелічити форми
Сторінки, перевірити токен і провести разовий обмін токенів при
налаштуванні інтеграції.

Форма модуля дзеркалить `app.services.sintegrum_client`: dataclass-результат
замість винятків (адмінка мусить показати помилку, а не впасти, а черга --
вирішити, ретраїти чи ні), ретраї лише на транзієнтних збоях, таймаут на
кожному запиті, стеля кількості сторінок при пагінації.

ВАЖЛИВО про портованість (розділ 3, частина C плану): модуль навмисно не
імпортує ані Flask, ані SQLAlchemy, ані моделі ІПРМ -- лише `requests`,
стандартну бібліотеку і спільний контракт `meta_contracts`. Конфігурацію
отримує ззовні: `from_settings` приймає будь-який об'єкт із потрібними
атрибутами. Завдяки цьому файл переноситься в MM Medic як є.
"""
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Any, Optional

import requests

# Коди помилок Meta живуть у контракті, а не тут: проти того самого
# переліку пишеться тестовий двійник клієнта, а він лежить у `tests/`,
# звідки застосунок імпортувати не має права. Розшифровка транзієнтних:
#
#   1   -- невідома помилка на боці Meta (API Unknown), класика «спробуйте ще»;
#   2   -- сервіс тимчасово недоступний (API Service);
#   4   -- застосунок вичерпав погодинну квоту (API Too Many Calls);
#   17  -- квоту вичерпав користувач або токен (API User Too Many Calls);
#   341 -- тимчасовий ліміт дії (Application limit reached).
#
# Спільне в них одне: причина минає сама, а дані не втрачені. Решта
# помилок -- діагноз, а не збій, і ретрай лише крутить чергу намарно.
from app.services.meta_contracts import (
    DEFAULT_GRAPH_VERSION,
    LEAD_FIELDS,
    MetaResult,
    RETRYABLE_ERROR_CODES,
    TOKEN_ERROR_CODE,
)

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = 'https://graph.facebook.com'

TIMEOUT = (3.0, 10.0)  # (connect, read)
_USER_AGENT = 'iprm-meta-leads/1.0'
_MAX_ATTEMPTS = 3          # 1 початкова спроба + 2 ретраї на транзієнтних збоях
_RETRY_BACKOFF = 0.4       # секунди, множаться на номер спроби

# Стеля сторінок при обході `paging.next`. Запобіжник проти нескінченного
# циклу, якщо Meta почне віддавати курсор на ту саму сторінку: 20 * 100 --
# дві тисячі лідів за один прогін звірки, що на порядки більше за реальний
# добовий обсяг.
_MAX_PAGES = 20
_DEFAULT_LIMIT = 100

# HTTP-коди, які ретраїмо незалежно від тіла відповіді: 5xx -- збій на боці
# Meta, 429 -- ліміт частоти, обидва минають самі.
_RETRYABLE_HTTP_STATUS = (429,)

# Що вирізати з текстів помилок. `requests` вкладає повний URL у текст
# винятку при обриві з'єднання, а в URL лежить токен -- і він осів би в
# `MetaLeadEvent.last_error`, у логах і на екрані адмінки.
_SECRET_QUERY_RE = re.compile(
    r'((?:access_token|input_token|fb_exchange_token|client_secret|appsecret_proof)=)'
    r'[^&\s\'")]+',
    re.IGNORECASE,
)

#: Ознака «токен бере сам клієнт». None означає протилежне -- «запит без
#: токена», бо авторизація вже лежить у явних параметрах (обмін токенів).
_CLIENT_TOKEN = object()


class MetaConfigError(Exception):
    """Інтеграцію вимкнено або недоналаштовано (немає App ID, секрету, токена)."""


class MetaGraphClient:
    """Тонкий HTTP-клієнт Graph API у межах потреб Lead Ads."""

    def __init__(self, app_id: str, app_secret: str, access_token: str,
                 version: str = DEFAULT_GRAPH_VERSION):
        self.app_id = (app_id or '').strip()
        self.app_secret = (app_secret or '').strip()
        self.access_token = (access_token or '').strip()
        self.version = (version or DEFAULT_GRAPH_VERSION).strip().strip('/')

    # ---- конструювання з налаштувань ----
    @classmethod
    def from_settings(cls, site_settings, require_token: bool = True) -> 'MetaGraphClient':
        """Клієнт із рядка налаштувань.

        Тип аргументу навмисно не перевіряємо і читаємо все через `getattr`:
        модуль не знає ані про `SiteSettings`, ані про SQLAlchemy.

        `require_token=False` потрібен рівно одному сценарію -- кнопкам
        первинного налаштування в адмінці. Page token там ще не існує, його
        саме й отримують (`exchange_long_lived_user_token` -> `get_page_token`),
        тож вимога токена зробила б перший крок неможливим.
        """
        if not getattr(site_settings, 'meta_leads_enabled', False):
            raise MetaConfigError('Інтеграцію з Meta Lead Ads вимкнено')

        app_id = (getattr(site_settings, 'meta_app_id', '') or '').strip()
        app_secret = (getattr(site_settings, 'meta_app_secret', '') or '').strip()
        access_token = (getattr(site_settings, 'meta_page_token', '') or '').strip()
        version = (getattr(site_settings, 'meta_graph_version', '') or '').strip()

        if not app_id:
            raise MetaConfigError('Не вказано App ID застосунку Meta')
        if not app_secret:
            raise MetaConfigError('Не задано App Secret застосунку Meta')
        if require_token and not access_token:
            raise MetaConfigError(
                'Немає Page Access Token: обміняйте User token у налаштуваннях'
            )

        return cls(app_id, app_secret, access_token,
                   version=version or DEFAULT_GRAPH_VERSION)

    # ---- підпис запитів ----
    def _appsecret_proof(self, token: str) -> Optional[str]:
        """HMAC-SHA256 токена ключем App Secret.

        Якщо в застосунку Meta увімкнено «Require App Secret Proof», запит
        без цього параметра відхиляється -- і виглядає це як зламаний
        токен, хоча токен цілий. Тому проф іде з кожним запитом, де є що
        підписувати.
        """
        if not token or not self.app_secret:
            return None
        return hmac.new(
            self.app_secret.encode('utf-8'), token.encode('utf-8'), hashlib.sha256,
        ).hexdigest()

    # ---- транспорт ----
    def _request(self, method: str, path: str, params: Optional[dict] = None,
                 data: Optional[dict] = None, token: Any = _CLIENT_TOKEN) -> MetaResult:
        """Запит до версійованого шляху Graph API.

        Версія береться з `self.version`, а не з константи: Meta виводить
        версії з ужитку за розкладом, і підняти її має бути можна з
        налаштувань, без релізу.
        """
        url = f'{GRAPH_BASE_URL}/{self.version}{path}'
        query = dict(params or {})
        if token is _CLIENT_TOKEN:
            token = self.access_token
        if token:
            query['access_token'] = token
            proof = self._appsecret_proof(token)
            if proof:
                query['appsecret_proof'] = proof
        return self._send(method, url, query, data)

    def _send(self, method: str, url: str, params: Optional[dict],
              data: Optional[dict]) -> MetaResult:
        """Один HTTP-виклик із ретраями на транзієнтних збоях."""
        headers = {'Accept': 'application/json', 'User-Agent': _USER_AGENT}

        last = MetaResult(ok=False, error='Не вдалося виконати запит до Graph API',
                          retryable=True)
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = requests.request(
                    method, url, params=params, data=data,
                    headers=headers, timeout=TIMEOUT,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = MetaResult(
                    ok=False, retryable=True,
                    error=_scrub(f'Немає зв\'язку з Graph API: {exc}'),
                )
                self._backoff(attempt)
                continue
            except requests.RequestException as exc:
                # Помилка формування запиту -- від повтору не полагодиться.
                return MetaResult(ok=False, retryable=False,
                                  error=_scrub(f'Помилка запиту до Graph API: {exc}'))

            try:
                payload = response.json()
            except ValueError:
                payload = None

            if response.ok:
                return MetaResult(ok=True, http_status=response.status_code, data=payload)

            failure = _failure_result(response, payload)
            if failure.retryable and attempt < _MAX_ATTEMPTS - 1:
                last = failure
                self._backoff(attempt)
                continue
            return failure

        return last

    @staticmethod
    def _backoff(attempt: int) -> None:
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_RETRY_BACKOFF * (attempt + 1))

    # ---- пагінація ----
    def _collect(self, result: MetaResult) -> MetaResult:
        """Зібрати всі сторінки списку в один список.

        Meta віддає `{'data': [...], 'paging': {'next': '<повний URL>'}}`.
        Курсор уже містить і токен, і проф, тому наступну сторінку тягнемо
        URL-ом як є, нічого не дописуючи.
        """
        if not result.ok:
            return result

        collected = []
        payload = result.data
        pages = 0

        while True:
            rows = payload.get('data') if isinstance(payload, dict) else None
            if isinstance(rows, list):
                collected.extend(rows)
            pages += 1

            paging = payload.get('paging') if isinstance(payload, dict) else None
            next_url = paging.get('next') if isinstance(paging, dict) else None
            if not next_url:
                break
            if pages >= _MAX_PAGES:
                logger.warning(
                    'Meta: досягнуто межу в %d сторінок, вибірка може бути неповною',
                    _MAX_PAGES,
                )
                break

            page = self._send('GET', next_url, None, None)
            if not page.ok:
                return page
            payload = page.data

        return MetaResult(ok=True, http_status=result.http_status, data=collected)

    # ---- ліди ----
    def get_lead(self, leadgen_id) -> MetaResult:
        """Повний лід за ідентифікатором з вебхука.

        Перелік полів живе в контракті (`LEAD_FIELDS`), бо від нього
        залежить, що зможе розібрати нормалізація.
        """
        return self._request('GET', f'/{leadgen_id}', params={
            'fields': ','.join(LEAD_FIELDS),
        })

    def list_form_leads(self, form_id, since_ts=None,
                        limit: int = _DEFAULT_LIMIT) -> MetaResult:
        """Ліди однієї форми, посторінково; `data` -- плаский список.

        `since_ts` -- unix-час, від якого брати (звірка дивиться назад на
        кілька годин). Фільтр рахує сам Meta: тягнути всю історію форми і
        відсіювати на своєму боці означало б десятки сторінок на кожен
        прогін.

        `limit` -- розмір СТОРІНКИ, а не стеля вибірки: решту доберемо по
        `paging.next` до `_MAX_PAGES`.
        """
        params = {
            'fields': ','.join(LEAD_FIELDS),
            'limit': str(limit),
        }
        if since_ts is not None:
            params['filtering'] = json.dumps([{
                'field': 'time_created',
                'operator': 'GREATER_THAN',
                'value': int(since_ts),
            }])
        return self._collect(self._request('GET', f'/{form_id}/leads', params=params))

    def list_page_forms(self, page_id) -> MetaResult:
        """Форми Сторінки; `data` -- плаский список зі `status` кожної."""
        return self._collect(self._request('GET', f'/{page_id}/leadgen_forms', params={
            'fields': 'id,name,status,locale,leads_count',
            'limit': str(_DEFAULT_LIMIT),
        }))

    # ---- токен ----
    def debug_token(self) -> MetaResult:
        """Стан поточного токена: `is_valid`, `expires_at`, `scopes`.

        `expires_at = 0` означає безстроковий -- саме таким і має бути Page
        token, обміняний через довгоживучий User token.

        Викликається під App Access Token (`app_id|app_secret`): перевіряти
        токен ним самим безглуздо -- відкликаний токен не зміг би й
        запитати про себе. `appsecret_proof` тут не додаємо, бо секрет уже
        всередині самого App Access Token.
        """
        result = self._request('GET', '/debug_token', token=None, params={
            'input_token': self.access_token,
            'access_token': f'{self.app_id}|{self.app_secret}',
        })
        if result.ok and isinstance(result.data, dict) \
                and isinstance(result.data.get('data'), dict):
            # Meta загортає відповідь у зайвий рівень `data`.
            return MetaResult(ok=True, http_status=result.http_status,
                              data=result.data['data'])
        return result

    def exchange_long_lived_user_token(self, short_token: str) -> MetaResult:
        """Короткоживучий User token -> довгоживучий (близько 60 діб).

        Перший крок ланцюжка з розділу 1.4 плану. Авторизація тут -- пара
        client_id/client_secret, тому власний токен клієнта в запит не йде.
        """
        return self._request('GET', '/oauth/access_token', token=None, params={
            'grant_type': 'fb_exchange_token',
            'client_id': self.app_id,
            'client_secret': self.app_secret,
            'fb_exchange_token': short_token,
        })

    def get_page_token(self, page_id, user_token: str) -> MetaResult:
        """Page Access Token Сторінки під довгоживучим User token.

        Такий Page token безстроковий -- рівно те, чого вимагає критерій
        приймання N8: пережити перезапуск без ручного оновлення.
        """
        return self._request('GET', f'/{page_id}', token=user_token, params={
            'fields': 'access_token,name',
        })

    def subscribe_page(self, page_id) -> MetaResult:
        """Підписати Сторінку на події `leadgen` для нашого застосунку.

        Без цієї підписки вебхук налаштований, але мовчить: Meta не має
        куди слати події зі Сторінки.
        """
        return self._request('POST', f'/{page_id}/subscribed_apps', data={
            'subscribed_fields': 'leadgen',
        })


# --- розбір помилок -------------------------------------------------------

def _scrub(text: str) -> str:
    """Прибрати токени й секрети з тексту, що піде в лог і в БД."""
    return _SECRET_QUERY_RE.sub(r'\1<hidden>', text or '')


def _failure_result(response, payload) -> MetaResult:
    """`MetaResult` з відповіді-помилки Graph API.

    Код беремо з ТІЛА (`{"error": {"code": ...}}`), а не з HTTP-статусу:
    Meta віддає 400 і на вичерпану квоту (мине саме), і на протухлий токен
    (не мине ніколи). За статусом ці два випадки не розрізнити, а рішення
    «ретраїти чи ні» ухвалюється саме тут.
    """
    error = payload.get('error') if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        error = {}

    code = error.get('code')
    subcode = error.get('error_subcode')
    message = error.get('message') or error.get('error_user_msg') or ''
    err_type = error.get('type') or ''
    fbtrace_id = error.get('fbtrace_id') or ''

    status = response.status_code
    if code == TOKEN_ERROR_CODE:
        retryable = False
    elif code in RETRYABLE_ERROR_CODES:
        retryable = True
    elif code is not None:
        # Meta назвала конкретну причину, і вона не з транзієнтних --
        # повтор нічого не змінить.
        retryable = False
    else:
        retryable = status >= 500 or status in _RETRYABLE_HTTP_STATUS

    parts = [f'Meta {status}']
    if code is not None:
        parts.append(f'code={code}' + (f'/{subcode}' if subcode else ''))
    if err_type:
        parts.append(err_type)
    text = ' '.join(parts)
    if message:
        text = f'{text}: {message}'
    elif not error:
        text = f'{text}: {(response.text or "")[:200]}'
    if fbtrace_id:
        text = f'{text} (fbtrace {fbtrace_id})'

    return MetaResult(ok=False, http_status=status, data=payload,
                      error=_scrub(text), retryable=retryable)
