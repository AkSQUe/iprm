"""Обкладинки онлайн-курсів із Sintegrum.

Фід курсу віддає недокументоване поле `avatar_link` -- публічне посилання на
файл на fs1.sintegrum.com (у документації є лише `avatar_id`, і ендпоінта
файлів там немає). Картинку ми НЕ показуємо цим посиланням напряму, а
затягуємо у власний медіа-реєстр:

* сторонній домен не треба вносити в img-src CSP;
* MediaFile дає WebP і варіант `card`, тобто ту саму вагу й формат, що в усіх
  інших картках сайту;
* обкладинка лишається на місці, навіть якщо їхній файловий сервер ляже або
  токен у посиланні зміниться.

Редакторський вибір недоторканний: якщо у курсу вже стоїть card_media без
нашої мітки `card_avatar_src`, значить зображення поставила людина, і
синхронізація його не чіпає.
"""
import logging
import os
import tempfile

import requests

from app.extensions import db
from app.services import media_service

logger = logging.getLogger(__name__)

TIMEOUT = (3.0, 15.0)  # (connect, read)
_USER_AGENT = 'iprm-sintegrum/1.0'
# Запобіжник проти велетенського файлу: обкладинки там -- сотні кілобайт.
_MAX_BYTES = 12 * 1024 * 1024


def cover_link(payload):
    """Посилання на обкладинку з payload курсу (порожньо -- немає)."""
    if not isinstance(payload, dict):
        return ''
    return (payload.get('avatar_link') or '').strip()


def needs_cover(course, link):
    """Чи треба тягнути обкладинку саме зараз."""
    if not link:
        return False
    # Ця ж картинка вже лежить у реєстрі.
    if course.card_avatar_src == link and course.card_media_id:
        return False
    # Зображення поставили руками -- чуже посилання його не заміщає.
    if course.card_media_id and not course.card_avatar_src:
        return False
    return True


def _download(link):
    """Завантажити файл у тимчасовий шлях. Повертає (path, error)."""
    try:
        response = requests.get(
            link, timeout=TIMEOUT, stream=True,
            headers={'User-Agent': _USER_AGENT},
        )
    except requests.RequestException as exc:
        return None, f'мережа: {exc}'

    with response:
        if response.status_code != 200:
            return None, f'HTTP {response.status_code}'
        ctype = (response.headers.get('Content-Type') or '').lower()
        if not ctype.startswith('image/'):
            return None, f'не зображення (Content-Type: {ctype or "невідомо"})'

        fd, path = tempfile.mkstemp(prefix='sintegrum-cover-')
        size = 0
        try:
            with os.fdopen(fd, 'wb') as fh:
                for chunk in response.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > _MAX_BYTES:
                        raise ValueError('файл завеликий')
                    fh.write(chunk)
        except (OSError, ValueError, requests.RequestException) as exc:
            _remove(path)
            return None, str(exc)

    return path, None


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        logger.warning('Не вдалося прибрати тимчасовий файл %s', path)


def sync_cover(course):
    """Затягнути обкладинку курсу з Sintegrum у медіа-реєстр.

    Повертає True, якщо картинку справді оновлено. Ніколи не кидає: збита
    обкладинка не має зривати синхронізацію каталогу.
    """
    link = cover_link(course.remote_payload)
    if not needs_cover(course, link):
        return False

    path, error = _download(link)
    if error:
        logger.warning('Обкладинка курсу %s не завантажилась (%s): %s',
                       course.sintegrum_id, link, error)
        return False

    try:
        media, error = media_service.create_from_path(
            path, original_name=os.path.basename(link) or 'sintegrum-cover',
            entity_type='online_course', entity_id=course.id,
            usage_type='card', alt_text=course.effective_title,
        )
    except Exception:
        logger.exception('Обкладинка курсу %s: збій обробки', course.sintegrum_id)
        return False
    finally:
        _remove(path)

    if error:
        logger.warning('Обкладинка курсу %s не обробилась: %s',
                       course.sintegrum_id, error)
        return False

    # Ім'я файлу читабельне, як і в решти сутностей.
    media_service.rename_for_entity(media, course.slug)

    previous = course.card_media
    course.card_media_id = media.id
    course.card_avatar_src = link
    # Стару НАШУ копію прибираємо: інакше кожна заміна картинки на боці
    # Sintegrum лишала б у реєстрі сироту. Ручне зображення сюди не потрапляє
    # (needs_cover його відсіює).
    if previous is not None and previous.id != media.id:
        db.session.flush()
        media_service.delete_media(previous)

    logger.info('Обкладинка курсу %s оновлена: media %s',
                course.sintegrum_id, media.id)
    return True
