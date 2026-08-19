"""Фейк Graph API + будівники payload-ів Meta Lead Ads.

Навіщо окремий модуль, а не мок у кожному тесті:

* доступів Meta на момент розробки немає, тож **сім критеріїв приймання з
  восьми** перевіряються саме тут (див. розділ 8 плану). Це не тимчасова
  заглушка на час очікування доступів, а основний інструмент перевірки;
* черга (`meta_lead_queue`) пишеться паралельно з клієнтом
  (`meta_graph_client`) -- без фейка вона не мала б проти чого писатися;
* формат відповіді Graph API нетривіальний (`field_data` -- список
  `{name, values}`, а не dict), і копія цього знання в кожному тесті
  розійшлася б із реальністю на першій же правці.

Фейк реалізує поверхню `MetaGraphClient` із `app/services/meta_contracts.py`
і повертає ті самі `MetaResult`. Ніякої мережі.

**Цей файл не змінює виконавець частини** -- він спільний, як і сам
контракт. Потрібна нова поведінка (новий тип збою, нове поле) -- через
ведучого.
"""
import hashlib
import hmac
import json
from datetime import datetime, timezone

from app.services.meta_contracts import (
    DEFAULT_GRAPH_VERSION,
    RETRYABLE_ERROR_CODES,
    TOKEN_ERROR_CODE as _TOKEN_ERROR_CODE,
    MetaResult,
)


# --- будівники payload-ів -------------------------------------------------

def make_field_data(**answers):
    """Відповіді форми у форматі Graph API.

    Meta віддає СПИСОК `{'name': ..., 'values': [...]}`, а не dict, і
    значення завжди у списку -- навіть коли воно одне. Тест, написаний під
    dict, зелений на фікстурі й мертвий на проді.

    >>> make_field_data(email='a@b.co')
    [{'name': 'email', 'values': ['a@b.co']}]
    """
    return [
        {'name': name, 'values': [value] if not isinstance(value, list) else list(value)}
        for name, value in answers.items()
    ]


def make_lead(leadgen_id='1000000000000001', created_time=None, **overrides):
    """Відповідь Graph API на `GET /{leadgen_id}`.

    Дефолт -- повний, «щасливий» лід: є і пошта, і телефон, і кампанія.
    Часткові випадки збираються через overrides, зокрема
    ``field_data=make_field_data(...)``.
    """
    if created_time is None:
        created_time = '2026-08-18T10:14:12+0000'
    lead = {
        'id': str(leadgen_id),
        'created_time': created_time,
        'ad_id': '23851234567890999',
        'ad_name': 'PRP -- відео 15с',
        'adset_id': '23851234567890555',
        'adset_name': 'Лікарі 28-55, Київ',
        'campaign_id': '23851234567890123',
        'campaign_name': 'PRP серпень',
        'form_id': '9988776655',
        'platform': 'ig',
        'is_organic': False,
        'field_data': make_field_data(
            full_name='Олена Ковальчук',
            email='olena@example.com',
            phone_number='+380671234567',
        ),
    }
    lead.update(overrides)
    return lead


def make_webhook_value(leadgen_id='1000000000000001', page_id='555000111',
                       form_id='9988776655', created_time=None, **overrides):
    """Вміст `entry[].changes[].value` вебхука leadgen.

    Вебхук приносить ЛИШЕ ідентифікатори -- жодного поля форми. Саме тому
    прийом і розбір розведені по різних частинах роботи.
    """
    value = {
        'leadgen_id': str(leadgen_id),
        'page_id': str(page_id),
        'form_id': str(form_id),
        'ad_id': '23851234567890999',
        'adgroup_id': '23851234567890555',
        'created_time': created_time if created_time is not None else 1755511452,
    }
    value.update(overrides)
    return value


def make_webhook_body(values=None, page_id='555000111'):
    """Повне тіло POST-запиту вебхука (об'єкт `page` з entry[]/changes[])."""
    if values is None:
        values = [make_webhook_value(page_id=page_id)]
    return {
        'object': 'page',
        'entry': [{
            'id': str(page_id),
            'time': 1755511453,
            'changes': [{'field': 'leadgen', 'value': v} for v in values],
        }],
    }


def sign_webhook(body, app_secret):
    """(raw_bytes, значення заголовка X-Hub-Signature-256).

    Підпис рахується по СИРОМУ тілу, тож і тест мусить слати рівно ті
    байти, які підписав: сериалізація на боці тесту й на боці клієнта
    інакше розійдуться пробілами, і перевірка підпису «зламається» без
    жодного дефекту.
    """
    raw = json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    digest = hmac.new(app_secret.encode('utf-8'), raw, hashlib.sha256).hexdigest()
    return raw, f'sha256={digest}'


# --- фейк клієнта ---------------------------------------------------------

class FakeMetaGraphClient:
    """Двійник `MetaGraphClient` без мережі.

    Використання:

        client = FakeMetaGraphClient(leads=[make_lead('111')])
        client.get_lead('111').data          # -> dict ліда
        client.get_lead('999').ok            # -> False (немає такого)

    Збої вставляються явно, бо перевіряти треба саме їх: черга мусить
    ретраїти транзієнтне і НЕ ретраїти протухлий токен.
    """

    #: Аліаси на контракт -- щоб тести читалися як
    #: `FakeMetaGraphClient.RETRYABLE_CODES`, але джерело лишалося одне.
    #: Своїх копій тут немає навмисно: розбіжність фейка з клієнтом дала б
    #: зелений тест на червоному коді.
    RETRYABLE_CODES = RETRYABLE_ERROR_CODES
    TOKEN_ERROR_CODE = _TOKEN_ERROR_CODE

    def __init__(self, leads=None, forms=None, version=DEFAULT_GRAPH_VERSION,
                 token_valid=True, token_expires_at=0):
        self.version = version
        self._leads = {str(l['id']): l for l in (leads or [])}
        self._forms = list(forms or [{
            'id': '9988776655',
            'name': 'Плазмотерапія -- консультація',
            'status': 'ACTIVE',
        }])
        self.token_valid = token_valid
        #: 0 == безстроковий, як його віддає сам Meta для page token.
        self.token_expires_at = token_expires_at

        #: Черга запрограмованих збоїв: кожен наступний виклик знімає один.
        self._failures = []
        #: Журнал викликів -- (метод, аргументи). Для перевірок «скільки
        #: разів сходили» і «за який період просили».
        self.calls = []

    # -- програмування поведінки --

    def add_lead(self, lead):
        self._leads[str(lead['id'])] = lead
        return lead

    def fail_next(self, count=1, code=None, http_status=500, message='temporary'):
        """Наступні `count` викликів повернуть помилку.

        `code` за замовчуванням транзієнтний. Для перевірки «не ретраїмо»
        передавайте `code=FakeMetaGraphClient.TOKEN_ERROR_CODE`.
        """
        if code is None:
            code = self.RETRYABLE_CODES[1]
        for _ in range(count):
            self._failures.append((code, http_status, message))

    def _maybe_fail(self):
        if not self._failures:
            return None
        code, http_status, message = self._failures.pop(0)
        return MetaResult(
            ok=False,
            http_status=http_status,
            error=f'Meta error code={code}: {message}',
            retryable=code in self.RETRYABLE_CODES,
        )

    # -- поверхня MetaGraphClient --

    def get_lead(self, leadgen_id):
        self.calls.append(('get_lead', str(leadgen_id)))
        failure = self._maybe_fail()
        if failure is not None:
            return failure
        lead = self._leads.get(str(leadgen_id))
        if lead is None:
            # Meta віддає 400 на неіснуючий вузол, і це остаточно:
            # ретраїти «такого ліда немає» -- крутити чергу намарно.
            return MetaResult(
                ok=False, http_status=400,
                error=f'Unsupported get request: {leadgen_id}',
                retryable=False,
            )
        return MetaResult(ok=True, http_status=200, data=lead)

    def list_form_leads(self, form_id, since_ts=None, limit=100):
        self.calls.append(('list_form_leads', str(form_id), since_ts, limit))
        failure = self._maybe_fail()
        if failure is not None:
            return failure
        rows = [l for l in self._leads.values() if str(l.get('form_id')) == str(form_id)]
        if since_ts is not None:
            rows = [l for l in rows if _lead_ts(l) >= int(since_ts)]
        rows.sort(key=_lead_ts, reverse=True)
        return MetaResult(ok=True, http_status=200, data=rows[:limit])

    def list_page_forms(self, page_id):
        self.calls.append(('list_page_forms', str(page_id)))
        failure = self._maybe_fail()
        if failure is not None:
            return failure
        return MetaResult(ok=True, http_status=200, data=list(self._forms))

    def debug_token(self):
        self.calls.append(('debug_token',))
        failure = self._maybe_fail()
        if failure is not None:
            return failure
        return MetaResult(ok=True, http_status=200, data={
            'is_valid': self.token_valid,
            'expires_at': self.token_expires_at,
            'scopes': ['leads_retrieval', 'pages_show_list',
                       'pages_read_engagement', 'pages_manage_metadata'],
            'type': 'PAGE',
        })

    def exchange_long_lived_user_token(self, short_token):
        self.calls.append(('exchange_long_lived_user_token',))
        failure = self._maybe_fail()
        if failure is not None:
            return failure
        return MetaResult(ok=True, http_status=200, data={
            'access_token': f'long-{short_token}', 'expires_in': 5184000,
        })

    def get_page_token(self, page_id, user_token):
        self.calls.append(('get_page_token', str(page_id)))
        failure = self._maybe_fail()
        if failure is not None:
            return failure
        return MetaResult(ok=True, http_status=200, data={
            'id': str(page_id), 'access_token': f'page-token-{page_id}',
        })

    def subscribe_page(self, page_id):
        self.calls.append(('subscribe_page', str(page_id)))
        failure = self._maybe_fail()
        if failure is not None:
            return failure
        return MetaResult(ok=True, http_status=200, data={'success': True})


def _lead_ts(lead):
    """Unix-час створення ліда з рядка `created_time` Graph API."""
    raw = lead.get('created_time')
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).replace('Z', '+00:00')
    # Meta віддає зсув без двокрапки (+0000), який fromisoformat до 3.11
    # не розбирає. Нормалізуємо, бо на цьому падає рівно один тест із
    # десяти -- і завжди не там, де його шукають.
    if len(text) >= 5 and (text[-5] in '+-') and text[-3] != ':':
        text = f'{text[:-2]}:{text[-2:]}'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())
