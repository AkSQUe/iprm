"""Санітизація опційних регалій тренера (сертифікати, патенти, статті).

Дані з адмінки приходять як JSON. Не довіряємо:
  * URL посилань -- лише http/https (без javascript: тощо);
  * підписи/назви -- екрануємо (bleach, без HTML);
  * URL зображень сертифікатів -- лише локальні (/static/images/trainers/...).
"""
import logging
import re
from urllib.parse import urlparse

import bleach

from app.extensions import db
from app.models.media_file import MediaFile

logger = logging.getLogger(__name__)

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


def filter_owned_certificates(items, trainer, user):
    """Лишити з уже санітизованих позицій лише ті, що належать тренеру.

    Лише для кабінету тренера; адмінка довірена й сюди не ходить.
    `sanitize_certificates` перевіряє форму позиції, але не власника, а
    `attach_trainer_media` після збереження перепривʼязує кожен згаданий
    MediaFile до тренера і фізично перейменовує файл. Без цього фільтра
    тренер, підставивши чужий media_id, забирав би собі й перейменовував
    медіа іншого тренера.

    Позиція з media_id -- лише коли файл завантажив сам користувач або він
    уже належить цьому тренеру. Позиція без media_id -- лише коли така сама
    (за url) вже є в його сертифікатах: нову картинку тренер додає тільки
    завантаженням, яке дає media_id, тож «нова позиція без media_id» -- це
    або підробка, або чуже посилання. Чужа позиція відкидається ЦІЛКОМ, а не
    лише її media_id: інакше лишилось би посилання на чужий файл, який тренер
    і далі показував би як свій.
    """
    if not items:
        return []
    own_urls = {
        (c or {}).get('url') for c in (trainer.certificates or [])
        if isinstance(c, dict)
    }
    wanted = {it['media_id'] for it in items if it.get('media_id')}
    owned = set()
    if wanted:
        for media in MediaFile.query.filter(MediaFile.id.in_(wanted)).all():
            if media.uploaded_by == user.id or (
                    media.entity_type == 'trainer'
                    and media.entity_id == trainer.id):
                owned.add(media.id)
    out = []
    for it in items:
        mid = it.get('media_id')
        if mid:
            if mid in owned:
                out.append(it)
        elif it.get('url') in own_urls:
            out.append(it)
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


def _remap_refs(items, mapping, keys):
    """Замінити URL у dict-елементах JSON-списку за mapping {old: new}."""
    if not isinstance(items, list) or not mapping:
        return items
    out = []
    for it in items:
        if isinstance(it, dict):
            it = dict(it)
            for k in keys:
                if it.get(k) in mapping:
                    it[k] = mapping[it[k]]
        out.append(it)
    return out


def attach_trainer_media(trainer):
    """Прив'язати MediaFile (фото/сертифікати/патенти) до тренера після збереження.

    Виставляє entity_type/entity_id/usage_type, перейменовує файли у читабельну
    схему ({slug}-photo, {slug}-certificate-N, ...) і оновлює URL у JSON-полях.
    Відв'язані не видаляємо автоматично. Ідемпотентно.

    Спільна для адмінки й кабінету тренера: обидва шляхи зберігають
    Trainer.certificates через один і той самий sanitize_certificates, і
    прив'язка медіа мусить бути так само одна -- інакше адмінка перейменовує
    файли й знімає їх з-під `media-prune-orphans`, а кабінет тренера ні, і
    сертифікати, завантажені тренером самостійно, лишаються без
    entity_type/entity_id назавжди -- CLI-очищення осиротілих файлів рано чи
    пізно фізично прибере їх із диска, хоча вони й далі показані на сайті.
    """
    from app.services import media_service

    assignments = collect_media_ids(trainer)
    if not assignments:
        return
    rows = {m.id: m for m in MediaFile.query.filter(MediaFile.id.in_(list(assignments))).all()}
    # 1-based індекси в межах кожного usage (для імен -certificate-N / -patent-N).
    cert_idx = {c['media_id']: i for i, c in enumerate(
        [c for c in (trainer.certificates or []) if isinstance(c, dict) and c.get('media_id')], 1)}
    pat_idx = {p['media_id']: i for i, p in enumerate(
        [p for p in (trainer.patents or []) if isinstance(p, dict) and p.get('media_id')], 1)}

    mapping = {}
    for mid, usage in assignments.items():
        m = rows.get(mid)
        if not m:
            continue
        m.entity_type = 'trainer'
        m.entity_id = trainer.id
        m.usage_type = usage
        idx = cert_idx.get(mid) if usage == 'certificate' else (
            pat_idx.get(mid) if usage == 'patent' else None)
        mapping.update(media_service.rename_for_entity(m, trainer.slug, idx))

    if mapping:
        trainer.certificates = _remap_refs(trainer.certificates, mapping, ('url', 'thumb', 'card'))
        trainer.patents = _remap_refs(trainer.patents, mapping, ('image', 'thumb', 'card'))
    try:
        db.session.commit()
    except Exception:
        logger.exception('Failed to attach media to trainer %s', trainer.id)
        db.session.rollback()
