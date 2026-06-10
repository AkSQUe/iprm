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
# Зображення з медіа-реєстру (поза static, через /media/...). Лише WebP.
_MEDIA_IMG_RE = re.compile(r'^/media/(?!.*\.\.)[\w./-]+\.webp$')

# Запобіжник проти необмеженого зростання JSON-списків регалій/профілю.
_MAX_ITEMS = 50


def _is_img_url(value):
    """URL зображення валідний, якщо це локальний static- або media-шлях."""
    value = (value or '').strip()
    return bool(_LOCAL_IMG_RE.match(value) or _MEDIA_IMG_RE.match(value))


def _opt_media_id(value):
    """media_id -> позитивний int або None (приймає int і рядок-цифри)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


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
        if not _is_img_url(image):
            image = ''
        if not _is_img_url(thumb):
            thumb = image
        url = _clean_url(it.get('url'))
        label = _clean_text(it.get('label'), 300)
        if not (image or url):
            continue
        if not label:
            label = url or 'Патент'
        rec = {'image': image, 'thumb': thumb, 'label': label, 'url': url or ''}
        card = (it.get('card') or '').strip()
        if _is_img_url(card):
            rec['card'] = card
        mid = _opt_media_id(it.get('media_id'))
        if mid and image:
            rec['media_id'] = mid
        out.append(rec)
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
        if not _is_img_url(url):
            continue
        thumb = (it.get('thumb') or '').strip()
        if not _is_img_url(thumb):
            thumb = url
        rec = {
            'url': url,
            'thumb': thumb,
            'caption': _clean_text(it.get('caption'), 200),
        }
        card = (it.get('card') or '').strip()
        if _is_img_url(card):
            rec['card'] = card
        mid = _opt_media_id(it.get('media_id'))
        if mid:
            rec['media_id'] = mid
        out.append(rec)
    return out


def collect_media_ids(trainer):
    """Зібрати media_id, на які посилається тренер (photo + certs + patents).

    Повертає dict media_id -> usage_type для прив'язки MediaFile до тренера."""
    out = {}
    if getattr(trainer, 'photo_media_id', None):
        out[trainer.photo_media_id] = 'photo'
    for cert in (trainer.certificates or []):
        mid = _opt_media_id((cert or {}).get('media_id'))
        if mid:
            out.setdefault(mid, 'certificate')
    for pat in (trainer.patents or []):
        mid = _opt_media_id((pat or {}).get('media_id'))
        if mid:
            out.setdefault(mid, 'patent')
    return out
