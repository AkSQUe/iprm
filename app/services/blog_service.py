"""Бізнес-логіка блогу: slug, валідація/санітизація блоків контенту.

Контент допису -- упорядкований список блоків. Кожен блок: {type, data}.
Дані з браузера НІКОЛИ не довіряємо: текст проганяємо через bleach (вузький
whitelist інлайн-тегів), YouTube зберігаємо лише як 11-символьний video_id,
URL зображень приймаємо лише локальні (/static/images/blog/...). Невідомі типи
блоків і порожні блоки відкидаємо.
"""
import re
import unicodedata

import bleach

from app.extensions import db
from app.models.blog_post import BlogPost

# ---- Slug ----
_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e',
    'є': 'ie', 'ж': 'zh', 'з': 'z', 'и': 'y', 'і': 'i', 'ї': 'i', 'й': 'i',
    'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch',
    'ш': 'sh', 'щ': 'shch', 'ь': '', 'ю': 'iu', 'я': 'ia',
}


def slugify(text):
    """Укр/лат текст -> URL-safe slug (lowercase, дефіси)."""
    text = (text or '').strip().lower()
    out = []
    for ch in text:
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        elif unicodedata.category(ch).startswith('L') and ch.isalnum():
            # інші латинські літери з діакритикою -> ASCII-наближення
            norm = unicodedata.normalize('NFKD', ch).encode('ascii', 'ignore').decode()
            out.append(norm.lower() or '-')
        else:
            out.append('-')
    slug = re.sub(r'-+', '-', ''.join(out)).strip('-')
    return slug[:180] or 'post'


def generate_unique_slug(title, *, exclude_id=None):
    """Унікальний slug на основі заголовка (з суфіксом -2, -3 за потреби)."""
    base = slugify(title)
    candidate = base
    n = 2
    while True:
        q = BlogPost.query.filter_by(slug=candidate)
        if exclude_id is not None:
            q = q.filter(BlogPost.id != exclude_id)
        if not db.session.query(q.exists()).scalar():
            return candidate
        candidate = f'{base}-{n}'
        n += 1


# ---- Санітизація контенту ----
_INLINE_TAGS = ['b', 'strong', 'i', 'em', 'u', 'a', 'br', 'span']
_INLINE_ATTRS = {'a': ['href', 'title', 'rel', 'target'], 'span': []}
_PROTOCOLS = ['http', 'https', 'mailto']

_YT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')
_YT_URL_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})'
)
_LOCAL_IMG_RE = re.compile(r'^/static/images/blog/[\w./-]+$')

ALLOWED_BLOCK_TYPES = {
    'heading', 'paragraph', 'list', 'quote',
    'image', 'gallery', 'youtube', 'divider', 'callout',
}


def _clean_inline(value):
    """Інлайн-rich-text: лишаємо вузький набір тегів, решту екрануємо/прибираємо."""
    return bleach.clean(
        value or '', tags=_INLINE_TAGS, attributes=_INLINE_ATTRS,
        protocols=_PROTOCOLS, strip=True,
    ).strip()


def _clean_plain(value, limit=500):
    """Звичайний текст без HTML."""
    return bleach.clean(value or '', tags=[], strip=True).strip()[:limit]


def _extract_youtube_id(raw):
    raw = (raw or '').strip()
    if _YT_ID_RE.match(raw):
        return raw
    m = _YT_URL_RE.search(raw)
    return m.group(1) if m else None


def _clean_image_ref(item):
    """Один елемент зображення: лише локальні URL + санітизовані підписи."""
    if not isinstance(item, dict):
        return None
    url = (item.get('url') or '').strip()
    if not _LOCAL_IMG_RE.match(url):
        return None
    thumb = (item.get('thumb') or '').strip()
    if not _LOCAL_IMG_RE.match(thumb):
        thumb = url
    out = {
        'url': url,
        'thumb': thumb,
        'alt': _clean_plain(item.get('alt'), 200),
        'caption': _clean_plain(item.get('caption'), 300),
    }
    for key in ('width', 'height'):
        val = item.get(key)
        if isinstance(val, int) and 0 < val <= 10000:
            out[key] = val
    return out


def _sanitize_block(block):
    """Повертає очищений блок або None, якщо невалідний/порожній."""
    if not isinstance(block, dict):
        return None
    btype = block.get('type')
    if btype not in ALLOWED_BLOCK_TYPES:
        return None
    data = block.get('data') if isinstance(block.get('data'), dict) else {}

    if btype == 'heading':
        text = _clean_plain(data.get('text'), 250)
        if not text:
            return None
        level = data.get('level')
        level = level if level in (2, 3) else 2
        return {'type': 'heading', 'data': {'text': text, 'level': level}}

    if btype == 'paragraph':
        html = _clean_inline(data.get('html'))
        if not html:
            return None
        return {'type': 'paragraph', 'data': {'html': html}}

    if btype == 'list':
        style = data.get('style')
        style = style if style in ('ordered', 'unordered') else 'unordered'
        items = [_clean_inline(i) for i in (data.get('items') or []) if isinstance(i, str)]
        items = [i for i in items if i]
        if not items:
            return None
        return {'type': 'list', 'data': {'style': style, 'items': items}}

    if btype == 'quote':
        text = _clean_plain(data.get('text'), 1000)
        if not text:
            return None
        return {'type': 'quote', 'data': {'text': text, 'caption': _clean_plain(data.get('caption'), 200)}}

    if btype == 'image':
        ref = _clean_image_ref(data)
        return {'type': 'image', 'data': ref} if ref else None

    if btype == 'gallery':
        images = [_clean_image_ref(i) for i in (data.get('images') or [])]
        images = [i for i in images if i]
        if not images:
            return None
        return {'type': 'gallery', 'data': {'images': images}}

    if btype == 'youtube':
        vid = _extract_youtube_id(data.get('video_id') or data.get('url'))
        if not vid:
            return None
        return {'type': 'youtube', 'data': {'video_id': vid, 'caption': _clean_plain(data.get('caption'), 200)}}

    if btype == 'divider':
        return {'type': 'divider', 'data': {}}

    if btype == 'callout':
        html = _clean_inline(data.get('html'))
        if not html:
            return None
        style = data.get('style')
        style = style if style in ('info', 'warning', 'success') else 'info'
        return {'type': 'callout', 'data': {'html': html, 'style': style}}

    return None


def sanitize_content(blocks):
    """Очистити список блоків. Приймає list або None -> повертає list."""
    if not isinstance(blocks, list):
        return []
    cleaned = []
    for block in blocks:
        safe = _sanitize_block(block)
        if safe is not None:
            cleaned.append(safe)
    return cleaned


def auto_excerpt(blocks, limit=200):
    """Витягти короткий опис із першого текстового блоку (для excerpt/SEO)."""
    for block in blocks or []:
        if block.get('type') in ('paragraph', 'callout'):
            text = bleach.clean(block['data'].get('html', ''), tags=[], strip=True).strip()
            if text:
                return text[:limit].rsplit(' ', 1)[0] if len(text) > limit else text
        if block.get('type') == 'heading':
            text = block['data'].get('text', '').strip()
            if text:
                return text[:limit]
    return ''
