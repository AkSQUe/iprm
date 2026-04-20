import os
import re
from datetime import timezone

import bleach
from markupsafe import Markup


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
