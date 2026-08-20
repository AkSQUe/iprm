"""Клієнт зовнішнього API Sintegrum (LMS, де відбувається навчання).

Специфікація: https://new-api.sintegrum.com/api-swagger (OpenAPI 3.0),
вичитана копія -- docs/integrations/sintegrum-api.md. Усі шляхи мають вигляд
/external/{company}/..., авторизація -- Bearer-секрет у заголовку.

Дзеркалить підхід app.services.mm_medic_client: dataclass-результат замість
винятків, щоб адмінка могла показати помилку, а не впасти; ретраї лише на
транзієнтних збоях; таймаути на кожен запит.

ВАЖЛИВО про портованість (Р7 плану): модуль навмисно не імпортує ані Flask,
ані SQLAlchemy, ані моделі ІПРМ -- лише requests і стандартну бібліотеку.
Конфігурацію отримує ззовні (from_settings приймає будь-який об'єкт із
потрібними атрибутами). Завдяки цьому файл переноситься в інший проєкт як є.
"""
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

TIMEOUT = (3.0, 10.0)  # (connect, read)
_USER_AGENT = 'iprm-sintegrum/1.0'
_MAX_ATTEMPTS = 3          # 1 початкова спроба + 2 ретраї на транзієнтних збоях
_RETRY_BACKOFF = 0.4       # секунди, множаться на номер спроби

# Скільки сторінок каталогу максимум тягнемо за один прогін. Запобіжник проти
# нескінченного циклу, якщо Sintegrum почне віддавати ту саму сторінку:
# 50 * 100 = 5000 курсів, що на кілька порядків більше за реальний обсяг.
_MAX_PAGES = 50
_DEFAULT_PER_PAGE = 100

# Методи, повтор яких безпечний за визначенням.
_IDEMPOTENT_METHODS = frozenset({'GET', 'HEAD', 'PUT', 'DELETE', 'OPTIONS'})

# Статуси курсу (вони ж треки/позиції) на боці Sintegrum.
COURSE_STATUS_INACTIVE = 0
COURSE_STATUS_ACTIVE = 1
COURSE_STATUS_ARCHIVED = 2

# У учня шкала ІНША, і сплутати їх легко -- вони лежать поруч, а числа
# збігаються за формою. Саме на цьому ми й спіткнулись: створювали покупця
# зі status=1, вважаючи це "активний", а в Sintegrum одиниця означає
# "непідтверджений".
STUDENT_STATUS_BLOCKED = 0
STUDENT_STATUS_UNCONFIRMED = 1
STUDENT_STATUS_ACTIVE = 2
STUDENT_STATUS_ARCHIVED = 3


def _no_link(exc) -> str:
    return 'Немає зв' + chr(39) + 'язку з Sintegrum: ' + str(exc)


@dataclass
class SintegrumResult:
    ok: bool
    http_status: Optional[int] = None
    data: Any = None
    error: Optional[str] = None


class SintegrumConfigError(Exception):
    """Інтеграцію вимкнено або недоналаштовано (немає URL, аліаса чи ключа)."""


class SintegrumClient:
    """Тонкий HTTP-клієнт зовнішнього API Sintegrum."""

    def __init__(self, base_url: str, company: str, api_key: str):
        self.base_url = (base_url or '').rstrip('/')
        self.company = (company or '').strip()
        self.api_key = api_key

    # ---- конструювання з налаштувань ----
    @classmethod
    def from_settings(cls, site_settings) -> 'SintegrumClient':
        if not getattr(site_settings, 'sintegrum_enabled', False):
            raise SintegrumConfigError('Інтеграцію з Sintegrum вимкнено')
        base_url = (getattr(site_settings, 'sintegrum_api_base_url', '') or '').strip()
        company = (getattr(site_settings, 'sintegrum_company_alias', '') or '').strip()
        api_key = (getattr(site_settings, 'sintegrum_api_key', '') or '').strip()
        if not base_url:
            raise SintegrumConfigError('Не вказано базовий URL API Sintegrum')
        if not company:
            raise SintegrumConfigError('Не вказано аліас компанії в Sintegrum')
        if not api_key:
            raise SintegrumConfigError('Не задано ключ API Sintegrum')
        return cls(base_url, company, api_key)

    # ---- транспорт ----
    def _request(self, method: str, path: str, payload: Optional[dict] = None,
                 params: Optional[dict] = None) -> SintegrumResult:
        """Запит із ретраями на таймаутах, обривах з'єднання і 5xx.

        4xx вважаємо остаточними: невірний ключ чи аліас від повтору не
        полагодяться, а зайві спроби лише сповільнять сторінку адмінки.

        POST повторюємо ЛИШЕ тоді, коли з'єднання навіть не встановилось:
        читання, що впало в таймаут, і 500 у відповідь означають, що на тому
        боці запит могли й виконати. `POST /student` не ідемпотентний, тож
        повтор завів би другого учня на той самий email -- рівно те, від
        чого захищає пошук перед створенням. GET і DELETE повторюємо як
        раніше.
        """
        url = f'{self.base_url}/external/{self.company}{path}'
        if params:
            url = f'{url}?{urlencode(params)}'

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'application/json',
            'User-Agent': _USER_AGENT,
        }
        if payload is not None:
            headers['Content-Type'] = 'application/json; charset=utf-8'

        idempotent = method.upper() in _IDEMPOTENT_METHODS

        last = SintegrumResult(ok=False, error='Не вдалося виконати запит')
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = requests.request(
                    method, url, json=payload, headers=headers, timeout=TIMEOUT,
                )
            except requests.ConnectTimeout as exc:
                # З'єднання не встановилось -- сервер запиту не бачив,
                # тож повторити можна навіть неідемпотентний метод.
                last = SintegrumResult(ok=False, error=_no_link(exc))
                self._backoff(attempt)
                continue
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = SintegrumResult(ok=False, error=_no_link(exc))
                if not idempotent:
                    return last
                self._backoff(attempt)
                continue
            except requests.RequestException as exc:
                return SintegrumResult(ok=False, error=f'Помилка запиту: {exc}')

            try:
                data = response.json()
            except ValueError:
                data = None

            if response.ok:
                return SintegrumResult(ok=True, http_status=response.status_code, data=data)

            if response.status_code >= 500:
                last = SintegrumResult(
                    ok=False, http_status=response.status_code,
                    error=f'Sintegrum {response.status_code}',
                )
                if not idempotent:
                    return last
                self._backoff(attempt)
                continue

            return SintegrumResult(
                ok=False,
                http_status=response.status_code,
                data=data,
                error=self._error_text(response, data),
            )

        return last

    @staticmethod
    def _error_text(response, data) -> str:
        """Людський текст помилки. Ключ у повідомлення не потрапляє ніколи."""
        if response.status_code == 401:
            return 'Sintegrum 401: ключ API не прийнято'
        if response.status_code == 403:
            return 'Sintegrum 403: ключу бракує прав'
        if response.status_code == 404:
            return 'Sintegrum 404: не знайдено (перевірте аліас компанії)'
        if isinstance(data, dict):
            detail = data.get('message') or data.get('error') or data.get('name')
            if detail:
                return f'Sintegrum {response.status_code}: {detail}'
        return f'Sintegrum {response.status_code}: {(response.text or "")[:200]}'

    @staticmethod
    def _backoff(attempt: int) -> None:
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_RETRY_BACKOFF * (attempt + 1))

    # ---- курси (вони ж треки) ----
    def list_courses_page(self, page: int = 1, per_page: int = _DEFAULT_PER_PAGE,
                          sort: str = 'id') -> SintegrumResult:
        return self._request('GET', '/course', params={
            'page': str(page), 'per-page': str(per_page), 'sort': sort,
        })

    def list_all_courses(self, per_page: int = _DEFAULT_PER_PAGE) -> SintegrumResult:
        """Повний каталог посторінково.

        Ознака кінця -- порожня сторінка або сторінка, коротша за розмір
        (Sintegrum не віддає загальної кількості). Повторення вже баченого id
        теж зупиняє цикл: краще віддати те, що зібрано, ніж крутитись вічно.
        """
        collected = []
        seen_ids = set()

        for page in range(1, _MAX_PAGES + 1):
            result = self.list_courses_page(page=page, per_page=per_page)
            if not result.ok:
                return result

            items = result.data if isinstance(result.data, list) else []
            if not items:
                break

            fresh = [i for i in items if isinstance(i, dict) and i.get('id') not in seen_ids]
            if not fresh:
                logger.warning(
                    'Sintegrum: сторінка %d не дала жодного нового курсу, зупиняємось',
                    page,
                )
                break

            for item in fresh:
                seen_ids.add(item.get('id'))
            collected.extend(fresh)

            if len(items) < per_page:
                break
        else:
            logger.warning(
                'Sintegrum: досягнуто межу в %d сторінок, каталог може бути неповним',
                _MAX_PAGES,
            )

        return SintegrumResult(ok=True, http_status=200, data=collected)

    # ---- учні ----
    def create_student(self, email: str, first_name: str = '', last_name: str = '',
                       phone: str = '', language: str = 'uk',
                       status: int = STUDENT_STATUS_ACTIVE) -> SintegrumResult:
        """Завести учня. За замовчуванням -- одразу активного.

        `status` тут зі шкали УЧНЯ (0 заблокований, 1 непідтверджений,
        2 активний, 3 архів), а не зі шкали курсу.
        """
        payload = {
            'email': email,
            'first_name': first_name,
            'last_name': last_name,
            'phone': phone,
            'language': language,
            'status': status,
        }
        return self._request('POST', '/student', {k: v for k, v in payload.items() if v != ''})

    def get_student(self, student_id: int) -> SintegrumResult:
        return self._request('GET', f'/student/{student_id}')

    def list_students(self, page: int = 1, per_page: int = _DEFAULT_PER_PAGE,
                      filters: Optional[dict] = None) -> SintegrumResult:
        """Список учнів. `filters` -- готові параметри фільтра партнера.

        Саме словник, а не зібраний рядок: у документації фільтр -- це набір
        параметрів із дужками (`filter[поле][оператор]=значення`). Рядок
        довелося б класти в ПАРАМЕТР `filter`, і його назва продублювалася б
        у власному значенні -- запит виглядав би як
        `?filter=filter[email][eq]=...`, і фільтрація мовчки не спрацьовувала.
        """
        params = {'page': str(page), 'per-page': str(per_page)}
        if filters:
            params.update(filters)
        return self._request('GET', '/student/list', params=params)

    # ---- службове ----
    def find_student_by_email(self, email: str) -> SintegrumResult:
        """Знайти студента за email. `data` -- словник або None, якщо немає.

        Потрібно перед створенням: та сама людина може купити другий курс, і
        завести її вдруге означало б два кабінети на один email, у кожному
        по половині навчання.

        Синтаксис фільтра -- як у документації партнера
        (`filter[<поле>][<оператор>]=<значення>`). Якщо він не спрацює,
        падати не можна: краще не знайти й піти шляхом створення, ніж
        зронити видачу доступу цілком. Саме тому збіг email перевіряється
        ще й тут, локально: відповідь, яку не відфільтрували, не має видати
        першого-ліпшого учня за свого.
        """
        result = self.list_students(
            per_page=_DEFAULT_PER_PAGE,
            filters={'filter[email][eq]': (email or '').strip()},
        )
        if not result.ok:
            return result

        rows = result.data if isinstance(result.data, list) else []
        needle = (email or '').strip().lower()
        for row in rows:
            if isinstance(row, dict) and (row.get('email') or '').lower() == needle:
                return SintegrumResult(ok=True, http_status=result.http_status,
                                       data=row)
        return SintegrumResult(ok=True, http_status=result.http_status, data=None)

    # ---- доступ до курсу ----
    #
    # У Sintegrum курс -- це "position": у схемі Course усі поля описані як
    # "The position id/name". Тому відкриття доступу до курсу виглядає як
    # призначення позиції користувачу.

    def assign_course(self, student_id: int, course_id: int) -> SintegrumResult:
        """Відкрити студенту доступ до курсу."""
        return self._request(
            'POST', f'/user/{student_id}/positions/{course_id}',
        )

    def assigned_positions(self, user_id: int) -> SintegrumResult:
        """Що людині справді призначено на боці партнера.

        Єдиний спосіб перевірити, що відкриття курсу спрацювало: сам
        `POST .../positions/...` відповідає порожнім 200, тобто "запит
        прийнято", а не "людина бачить курс".
        """
        return self._request('GET', f'/progress/assigned/{user_id}')

    def revoke_course(self, student_id: int, course_id: int) -> SintegrumResult:
        """Забрати доступ (повернення коштів)."""
        return self._request(
            'DELETE', f'/user/{student_id}/positions/{course_id}',
        )

    def get_config(self) -> SintegrumResult:
        return self._request('GET', '/config')

    def ping(self) -> SintegrumResult:
        """Найдешевша перевірка зв'язку для кнопки в адмінці.

        Свідомо смикаємо саме /course з per-page=1, а не /config: /config
        оголошено без схеми відповіді, тож незрозуміло, що вважати успіхом.
        Успіх тут означає рівно те, що потрібно інтеграції: ключ і аліас
        робочі, каталог читається.
        """
        result = self.list_courses_page(page=1, per_page=1)
        if result.ok and not isinstance(result.data, list):
            return SintegrumResult(
                ok=False, http_status=result.http_status,
                error='Sintegrum повернув несподіваний формат відповіді',
            )
        return result
