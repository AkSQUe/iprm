import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import bleach
from markupsafe import Markup


# Канонічний формат українського номера: +380 та 9 цифр (12 цифр загалом).
UA_PHONE_RE = re.compile(r'^\+380\d{9}$')
# ПІБ: лише українська кирилиця, апостроф, дефіс і пробіл. Латиниця/цифри
# заборонені (типова помилка -- розкладка клавіатури).
CYRILLIC_NAME_RE = re.compile(r"^[А-ЯЇІЄҐа-яїієґ'’\- ]+$")


def normalize_phone(value):
    """Звести телефон до канонічного +380XXXXXXXXX, де це можливо.

    Приймає поширені варіанти вводу (0XX..., 380..., з пробілами/дужками/
    дефісами). Якщо однозначно нормалізувати не вдається -- повертає
    '+<цифри>', і валідатор формату відхилить. None -> None, порожнє -> ''.
    """
    if value is None:
        return None
    digits = re.sub(r'\D', '', str(value))
    if not digits:
        return ''
    if digits.startswith('380') and len(digits) == 12:
        return '+' + digits
    if digits.startswith('0') and len(digits) == 10:
        return '+38' + digits            # 0XXXXXXXXX -> +380XXXXXXXXX
    if len(digits) == 9:                 # XXXXXXXXX (без коду й 0)
        return '+380' + digits
    return '+' + digits                  # лишаємо -> валідатор вирішить


def normalize_name(value):
    """Нормалізувати частину ПІБ: trim, схлопнути пробіли, кожне слово -- з
    великої літери (межі -- пробіл і дефіс), решта літер -- малі.

    Апостроф усередині слова НЕ робить наступну літеру великою
    (напр. «Мар'яна», а не «Мар'Яна»). Скасовує CAPS LOCK і
    випадкові ВЕЛИКІ літери. None -> None, порожнє -> ''.
    """
    if value is None:
        return None
    s = re.sub(r'\s+', ' ', str(value).strip())
    if not s:
        return ''

    def cap_word(word):
        return '-'.join(
            (seg[:1].upper() + seg[1:].lower()) if seg else seg
            for seg in word.split('-')
        )

    return ' '.join(cap_word(w) for w in s.split(' '))


# Київський час. Потрібен там, де межа доби має бути людською, а не UTC:
# «до 23:59 у день завершення заходу» в UTC означало б для когось «до обіду».
#
# Саме зона, а не фіксований зсув. Раніше тут стояло UTC+3 -- влітку це
# правда, але з останньої неділі жовтня Київ переходить на UTC+2, і кожен
# підпис часу, кожна межа фільтра по датах і кожна клітинка xlsx ставали на
# годину попереду. Помилка мовчазна: числа виглядають правдоподібно, просто
# не збігаються з годинником читача.
#
# УВАГА: та сама константа вже живе в `app/admin/_listing.py`,
# `app/services/xlsx_io.py` і `app/services/participant_service.py`. Тут вона
# оголошена як канонічна (поряд з `ensure_utc`, з якою завжди вживається); ті
# три копії варто звести сюди окремою правкою -- вони на шляху xlsx-експорту, і
# чіпати їх мимохідь означало б ризикнути ним без потреби.
KYIV = ZoneInfo('Europe/Kyiv')


def ensure_utc(dt):
    """Нормалізує datetime до timezone-aware UTC.

    Потрібно для порівнянь start_date з `datetime.now(timezone.utc)`:
    SQLite зберігає datetime без tz, тож при читанні приходить naive.
    На PostgreSQL це no-op -- колонка вже timezone-aware.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def to_kyiv(value):
    """Перевести datetime у київський час.

    Колонки лежать у UTC, а шаблони друкували їх без переведення: замовлення,
    оформлене о 00:40 київської ночі, показувалось учорашнім 21:40. Для
    підпису під очима людини це просто неправда.

    `date` (без часу) і None повертаються як є: у зсуві вони не потребують
    нічого, а формат дати від нього не залежить. Naive-значення вважаємо UTC
    -- те саме припущення, що й в `ensure_utc` (так їх віддає SQLite).
    """
    if not isinstance(value, datetime):
        return value
    return ensure_utc(value).astimezone(KYIV)


def kyiv_dt(value, fmt='%d.%m.%Y %H:%M'):
    """Jinja-фільтр `| kyiv`: підпис часу в київській зоні.

    Порожнє значення -> порожній рядок, щоб шаблон не обставляв кожен виклик
    перевіркою `{% if %}`.
    """
    value = to_kyiv(value)
    if value is None:
        return ''
    return value.strftime(fmt)

# Whitelist тегів, дозволених у rich-text полях адмінки (course.description,
# faq.answer). Все інше (скрипти, iframe, event handlers) видаляється.
RICH_TEXT_ALLOWED_TAGS = frozenset({
    'p', 'br', 'hr',
    'strong', 'b', 'em', 'i', 'u', 's', 'sub', 'sup', 'mark',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li',
    'blockquote', 'code', 'pre',
    'a', 'span', 'div',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'img',
})

RICH_TEXT_ALLOWED_ATTRIBUTES = {
    '*': ['class'],
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height', 'loading'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan', 'scope'],
}

RICH_TEXT_ALLOWED_PROTOCOLS = frozenset({'http', 'https', 'mailto', 'tel'})


def sanitize_rich_text(raw):
    """Повертає безпечний HTML-рядок, придатний для `| safe` у Jinja.

    Видаляє всі script/iframe/on* атрибути та невідомі теги. Якщо вхід
    порожній або None -- повертає порожній Markup.
    """
    if not raw:
        return Markup('')
    cleaned = bleach.clean(
        raw,
        tags=RICH_TEXT_ALLOWED_TAGS,
        attributes=RICH_TEXT_ALLOWED_ATTRIBUTES,
        protocols=RICH_TEXT_ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    return Markup(cleaned)


def uk_plural(n, one, few, many):
    """Українська плюралізація: uk_plural(2, 'блок', 'блоки', 'блоків') -> 'блоки'.

    1 -> one, 2-4 -> few, 5-20/0 -> many (з урахуванням 11-14 та складених
    числівників: 21 -> one, 22 -> few, 25 -> many).
    """
    try:
        n = abs(int(n))
    except (TypeError, ValueError):
        return many
    mod10, mod100 = n % 10, n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 10 <= mod100 < 20:
        return few
    return many


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:200]


def update_env_key(env_path, key, value):
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

    new_lines = []
    for line in lines:
        if line.strip().startswith(f'{key}='):
            new_lines.append(f'{key}={value}\n')
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f'{key}={value}\n')

    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
