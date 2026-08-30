"""Контракт між частинами інтеграції Meta Lead Ads.

Модуль існує з однієї причини: три частини роботи пишуться паралельно і
мусять зійтися без перехідників. `meta_graph_client` повертає `MetaResult`,
`meta_lead_ingest` -- `ParsedLead` і `ContactMatch`, `meta_lead_queue`
споживає все три. Якби кожна оголосила власний dataclass, черга писала б
конвертери між формами, які описують те саме.

**Цей файл не змінює виконавець частини.** Правка тут ламає код, який уже
написаний проти неї в іншому файлі й, можливо, в іншій сесії. Потрібна
зміна -- через ведучого, з попередженням усім, хто пише проти контракту.

Свідомо БЕЗ імпортів Flask, SQLAlchemy й моделей: контракт має читатися
(і переноситися) окремо від застосунку -- так само, як
`app/services/sintegrum_client.py`.
"""
from dataclasses import dataclass, field
from typing import Any, Optional


# Версія Graph API за замовчуванням. Живе тут, а не в клієнті, бо на неї
# дивиться і адмінка (показує адміну, з чим працює), і дефолт колонки
# SiteSettings.meta_graph_version. Meta виводить версії з ужитку за
# розкладом -- перед впровадженням звірити з чинною.
DEFAULT_GRAPH_VERSION = 'v21.0'

# Поля ліда, які просимо в Graph API. Перелік у контракті, а не в клієнті:
# від нього залежить, що зможе розібрати `normalize_field_data`, тож
# розширення переліку -- це зміна контракту, а не деталь клієнта.
LEAD_FIELDS = (
    'id',
    'created_time',
    'ad_id',
    'ad_name',
    'adset_id',
    'adset_name',
    'campaign_id',
    'campaign_name',
    'form_id',
    'platform',
    'is_organic',
    'field_data',
)

# Поля форми. Тут заради `questions`: у `field_data` ліда Meta кладе не
# текст обраного варіанта, а його внутрішній КЛЮЧ -- нижній регістр,
# пробіли підкресленнями (`ортопедія_/_травматологія`). Людський підпис
# живе ЛИШЕ у схемі форми: `questions[].label` для питання і
# `questions[].options[].value` для варіанта.
#
# Перелік у контракті з тієї самої причини, що й `LEAD_FIELDS`: проти
# нього пишуть і клієнт, і його тестовий двійник.
FORM_FIELDS = (
    'id',
    'name',
    'status',
    'locale',
    'leads_count',
    'questions{key,label,type,options{key,value}}',
)


# Коди помилок Meta, після яких має сенс повторити запит: причина минає
# сама, дані не втрачені. 1 -- API Unknown, 2 -- API Service, 4 -- квота
# застосунку, 17 -- квота токена, 341 -- тимчасовий ліміт дії.
#
# Живуть у контракті, а не в клієнті, з простої причини: проти цього
# переліку пишуть і клієнт, і його тестовий двійник, а двійник лежить у
# `tests/`, звідки застосунок не має права імпортувати. Дві копії списку
# розійшлися б на першому новому коді -- і розійшлися б МОВЧКИ, бо тест на
# фейку лишався б зеленим.
RETRYABLE_ERROR_CODES = (1, 2, 4, 17, 341)

# Протухлий або відкликаний токен. Свідомо НЕ транзієнтний: від повтору не
# полагодиться, лікується ротацією в адмінці. Ретраї тут лише ховали б
# діагноз до вичерпання спроб.
TOKEN_ERROR_CODE = 190


@dataclass
class MetaResult:
    """Результат одного звернення до Graph API.

    Dataclass, а не виняток: адмінка мусить показати помилку, а не впасти,
    а черга -- вирішити, ретраїти чи ні. Той самий підхід, що
    `SintegrumResult` і `DispatchResult`.

    `retryable` вирішує КЛІЄНТ, бо лише він бачить код помилки Meta:
    протухлий токен (code=190) від повтору не полагодиться, а rate limit
    (code=4/17) -- полагодиться.
    """

    ok: bool
    http_status: Optional[int] = None
    data: Any = None
    error: Optional[str] = None
    retryable: bool = False


@dataclass
class ParsedLead:
    """Нормалізовані поля однієї заявки.

    `phone_e164` порожній означає «номер не розпізнано», а НЕ «номера
    немає»: сирий рядок лишається в `phone_raw`. Вигадувати за людину
    канонічну форму заборонено -- зіставлення за вигаданим номером зшиває
    картку з ким завгодно (див. коментар у `MedicalProfile._sync_phone_e164`).
    """

    email: Optional[str] = None
    phone_raw: Optional[str] = None
    phone_e164: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    #: Відповіді на питання, яких немає серед стандартних полів Meta.
    #: Набір змінюється щокампанії, тому dict, а не колонки.
    custom: dict = field(default_factory=dict)

    @property
    def has_contacts(self):
        """Чи є за чим шукати людину. Заявка без пошти й без номера --
        це не контакт, а рядок у звіті."""
        return bool(self.email or self.phone_e164 or self.phone_raw)


@dataclass
class ContactMatch:
    """Підсумок пошуку контакту під заявку.

    `user` -- до кого прив'язуємо. `conflict_user` -- другий контакт, на
    який вказала пошта, коли телефон вказав на інший; автоматичне злиття
    заборонене, рішення приймає людина.

    `extra_user_ids` -- решта контактів із тим самим номером. Телефон у
    базі НЕ унікальний (клініка з єдиним контактним телефоном -- звичайна
    річ), тож «точний збіг» цілком може дати кілька карток.
    """

    #: `User` або None; тип не анотуємо, щоб не тягти сюди моделі.
    user: Any = None
    #: Одне з MetaLead.MATCH_* -- 'phone' | 'email' | 'created' | 'none'.
    method: str = 'none'
    conflict_user: Any = None
    extra_user_ids: list = field(default_factory=list)
    #: Людиночитне пояснення для «потребує уваги»; порожнє -- усе чисто.
    reason: str = ''

    @property
    def needs_attention(self):
        return bool(self.conflict_user or self.extra_user_ids)
