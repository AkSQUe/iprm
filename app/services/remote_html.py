"""Очищення HTML, що прийшов із чужої системи.

Sintegrum віддає опис курсу готовою розміткою свого редактора. Поводитись
із нею можна трьома способами, і два з них погані:

* показати як текст -- людина бачить `<p><span style="color: rgb(0, 0, 0)">`
  замість опису. Саме так і виглядала картка курсу в адмінці;
* вставити як є через `|safe` -- ми віддаємо чужому редактору право
  виконувати що завгодно на наших сторінках, включно з `<script>`.

Тому третій: пропустити через bleach і лишити рівно ті теги, що потрібні
для читабельного опису.

ОКРЕМО ПРО style. Він вирізається завжди, і це не перестраховка: Sintegrum
проставляє `color: rgb(0, 0, 0)` майже кожному абзацу. У темній темі це
чорний текст на темному тлі, тобто опис курсу стає нечитабельним рівно
там, де ми нічого не зробили. Кольори й відступи -- справа нашої
дизайн-системи, а не чужого редактора.
"""
import re

import bleach

# Блокові теги потрібні: описи курсів -- це списки, підзаголовки й абзаци.
# Усе, чого тут немає (script, iframe, style, table, img), вирізається.
ALLOWED_TAGS = [
    'p', 'br', 'ul', 'ol', 'li', 'strong', 'b', 'em', 'i', 'u',
    'h3', 'h4', 'h5', 'blockquote', 'a',
]
ALLOWED_ATTRS = {'a': ['href', 'title', 'rel', 'target']}
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']

# Порожні абзаци-роздільники, якими рясніє чужий редактор.
_EMPTY_PARAGRAPH = re.compile(r'<p>(\s|&nbsp;|<br\s*/?>)*</p>', re.I)

# Теги, які треба прибрати РАЗОМ ІЗ ВМІСТОМ. bleach зі `strip=True` знімає
# сам тег, але лишає те, що всередині: `<script>alert(1)</script>` стає
# текстом `alert(1)`. Виконати його неможливо, проте показувати код у
# описі курсу безглуздо -- людина вирішить, що опис побитий.
_WITH_CONTENT = re.compile(
    r'<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>',
    re.I | re.S,
)


def clean_html(value):
    """Чужий HTML -> безпечний HTML, придатний до показу.

    Порожній вхід дає порожній рядок, а не None: результат іде просто в
    шаблон, і `None` там перетворився б на слово «None».
    """
    if not value:
        return ''
    value = _WITH_CONTENT.sub('', value)
    cleaned = bleach.clean(
        value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS, strip=True,
    )
    # Прибираємо порожні абзаци ПІСЛЯ очищення: до нього вони могли бути
    # не порожні, а лише зі span-ами, які щойно вирізало.
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _EMPTY_PARAGRAPH.sub('', cleaned)
    return cleaned.strip()


def to_text(value, limit=None):
    """Чужий HTML -> звичайний текст (для прев'ю, тем листів, мета-описів)."""
    if not value:
        return ''
    value = _WITH_CONTENT.sub('', value)
    text = bleach.clean(value, tags=[], strip=True)
    # `&nbsp;` після зняття тегів лишається сутністю; разом із переносами
    # рядків чужого редактора це дає рвані пробіли в мета-описі.
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:limit] if limit else text


def looks_like_html(value):
    """Чи є у рядку розмітка. Наш власний опис зазвичай простий текст."""
    return bool(value) and bool(re.search(r'<[a-zA-Z][^>]*>', value))
