"""Санітизація опційних регалій тренера (сертифікати, патенти, статті).

Дані з адмінки приходять як JSON. Не довіряємо:
  * URL посилань -- лише http/https (без javascript: тощо);
  * підписи/назви -- екрануємо (bleach, без HTML);
  * URL зображень сертифікатів -- лише локальні (/static/images/trainers/...).
"""
import re
from urllib.parse import urlparse

import bleach

_LOCAL_IMG_RE = re.compile(r'^/static/images/trainers/(?!.*\.\.)[\w./-]+\.(?:webp|jpe?g|png)$')

# Запобіжник проти необмеженого зростання JSON-списків регалій/профілю.
_MAX_ITEMS = 50


def _clean_text(value, limit):
    return bleach.clean(value or '', tags=[], strip=True).strip()[:limit]


def _clean_url(value):
    """Зовнішнє посилання: лише http/https з хостом. Інакше None."""
    value = (value or '').strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in ('http', 'https') and parsed.netloc:
        return value[:1000]
    return None


def sanitize_links(items):
    """[{label, url}] -> валідні зовнішні посилання. label порожній -> = url."""
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if len(out) >= _MAX_ITEMS:
            break
        if not isinstance(it, dict):
            continue
        url = _clean_url(it.get('url'))
        if not url:
            continue
        label = _clean_text(it.get('label'), 300) or url
        out.append({'label': label, 'url': url})
    return out


def sanitize_patents(items):
    """[{image, thumb, label, url}] -> патенти: опційний скан-зображення
    (локальне) + назва + опційне зовнішнє посилання. Запис лишаємо, якщо є
    зображення АБО посилання."""
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if len(out) >= _MAX_ITEMS:
            break
        if not isinstance(it, dict):
            continue
        image = (it.get('image') or '').strip()
        thumb = (it.get('thumb') or '').strip()
        if not _LOCAL_IMG_RE.match(image):
            image = ''
        if not _LOCAL_IMG_RE.match(thumb):
            thumb = image
        url = _clean_url(it.get('url'))
        label = _clean_text(it.get('label'), 300)
        if not (image or url):
            continue
        if not label:
            label = url or 'Патент'
        out.append({'image': image, 'thumb': thumb, 'label': label, 'url': url or ''})
    return out


def sanitize_text_list(text, max_items=_MAX_ITEMS, max_len=600):
    """Багаторядковий текст -> список пунктів (по рядку), без HTML.

    Універсальний санітайзер списків рядків: наукова діяльність, навички,
    освіта, досвід тощо. Приймає або готовий список (з моделі), або рядок
    (з textarea адмінки).
    """
    if isinstance(text, list):
        lines = [str(x) for x in text]
    else:
        lines = (text or '').splitlines()
    out = []
    for line in lines:
        item = _clean_text(line, max_len)
        if item:
            out.append(item)
        if len(out) >= max_items:
            break
    return out


# Зворотна сумісність: історична назва для наукової діяльності.
sanitize_research = sanitize_text_list


def sanitize_certificates(items):
    """[{url, thumb, caption}] -> валідні локальні зображення сертифікатів."""
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if len(out) >= _MAX_ITEMS:
            break
        if not isinstance(it, dict):
            continue
        url = (it.get('url') or '').strip()
        if not _LOCAL_IMG_RE.match(url):
            continue
        thumb = (it.get('thumb') or '').strip()
        if not _LOCAL_IMG_RE.match(thumb):
            thumb = url
        out.append({
            'url': url,
            'thumb': thumb,
            'caption': _clean_text(it.get('caption'), 200),
        })
    return out
