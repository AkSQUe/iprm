"""Material Symbols icon registry + render helper (server-side).

ICON_CODEPOINTS -- мапа назва-іконки -> Unicode-кодпойнт у self-hosted шрифті
Material Symbols Rounded. Шрифт субсетиться рівно до цих кодпойнтів
(scripts/subset-icons.py), тож served-woff2 важить ~6 КБ замість 407 КБ.

Іконки рендеряться через КОДПОЙНТ (а не лігатуру), тому субсет-шрифт не містить
літерних гліфів і lookup-ів лігатур -- це і дає малий розмір. Тому всі іконки
в шаблонах ставляться через глобал `icon('<name>')`, а не сирим <span>.

ЯК ДОДАТИ ІКОНКУ: впишіть назву нижче (кодпойнт -- з офіційного
codepoints-файлу Google) і запустіть `python scripts/subset-icons.py`,
щоб перегенерувати субсет-шрифт. CI-тест (tests/test_icons.py) перевіряє
синхронність шаблонів, мапи та шрифту.
"""
from markupsafe import Markup, escape

# AUTO-GENERATED block (scripts/subset-icons.py); тримати відсортованим за назвою.
ICON_CODEPOINTS = {
    'add': 0xe145,
    'add_link': 0xe178,
    'add_moderator': 0xe97d,
    'add_photo_alternate': 0xe43e,
    'apps': 0xe5c3,
    'arrow_forward': 0xe5c8,
    'article': 0xef87,
    'block': 0xf08c,
    'bolt': 0xea0b,
    'bug_report': 0xe868,
    'calendar_month': 0xebcc,
    'campaign': 0xef49,
    'check': 0xe668,
    'chevron_left': 0xe5cb,
    'chevron_right': 0xe5cc,
    'clear': 0xe5cd,
    'close': 0xe5cd,
    'collections': 0xe3d3,
    'content_copy': 0xe14d,
    'delete': 0xe92e,
    'download': 0xf090,
    'edit': 0xf097,
    'error': 0xf8b6,
    'event': 0xe878,
    'event_available': 0xe614,
    'event_busy': 0xe615,
    'event_upcoming': 0xf238,
    'format_bold': 0xe238,
    'format_italic': 0xe23f,
    'format_list_bulleted': 0xe241,
    'format_quote': 0xe244,
    'forum': 0xe8af,
    'forward_to_inbox': 0xf187,
    'group': 0xea21,
    'history': 0xe8b3,
    'horizontal_rule': 0xf108,
    'how_to_reg': 0xe174,
    'hub': 0xe9f4,
    'image': 0xe3f4,
    'inbox': 0xe156,
    'info': 0xe88e,
    'keep': 0xf027,
    'keyboard_arrow_down': 0xe313,
    'keyboard_arrow_up': 0xe316,
    'link': 0xe250,
    'looks_3': 0xe3fb,
    'mail': 0xe159,
    'mark_email_unread': 0xf18a,
    'menu_book': 0xea19,
    'more_vert': 0xe5d4,
    'notes': 0xe26c,
    'notifications': 0xe7f5,
    'open_in_new': 0xe89e,
    'outgoing_mail': 0xf0d2,
    'perm_media': 0xe8a7,
    'person_add': 0xea4d,
    'person_off': 0xe510,
    'picture_as_pdf': 0xe415,
    'priority_high': 0xe645,
    'quiz': 0xf04c,
    'refresh': 0xe5d5,
    'remove_moderator': 0xe9d4,
    'restart_alt': 0xf053,
    'reviews': 0xf07c,
    'school': 0xe80c,
    'search': 0xef7a,
    'send': 0xe163,
    'settings': 0xe8b8,
    'smart_display': 0xf06a,
    'table_view': 0xf1be,
    'title': 0xe264,
    'tune': 0xe429,
    'upload': 0xf09b,
    'upload_file': 0xe9fc,
    'verified': 0xef76,
    'visibility': 0xe8f4,
    'webhook': 0xeb92,
    'widgets': 0xe1bd,
    'workspace_premium': 0xe7af,
}


def render_icon(name, label=None, cls=None, size=None):
    """Зрендерити Material Symbols іконку через її кодпойнт.

    name  -- ключ із ICON_CODEPOINTS (напр. 'edit').
    label -- доступна назва: якщо задано, іконка НЕ декоративна
             (role="img" + aria-label). Інакше -- декоративна (aria-hidden).
    cls   -- додаткові CSS-класи.
    size  -- розмір у px (інлайновий font-size), напр. 18.

    Невідома назва -> порожній рядок (CI-тест не дасть такому потрапити в prod).
    """
    codepoint = ICON_CODEPOINTS.get(name)
    if codepoint is None:
        return Markup('')
    classes = 'material-symbols-rounded'
    if cls:
        classes = classes + ' ' + cls
    attrs = ['class="{}"'.format(escape(classes))]
    if size:
        attrs.append('style="font-size:{}px"'.format(int(size)))
    if label:
        attrs.append('role="img" aria-label="{}"'.format(escape(label)))
    else:
        attrs.append('aria-hidden="true"')
    glyph = '&#x{:x};'.format(codepoint)
    return Markup('<span {}>{}</span>'.format(' '.join(attrs), glyph))
