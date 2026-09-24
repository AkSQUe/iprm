"""Презентації тренерів до заходів: перевірка, запис на диск, адресати листа.

Файл перевіряється за СИГНАТУРОЮ, а не лише за розширенням: розширення
задає клієнт, і `virus.exe`, перейменований на `.pdf`, пройшов би. Ім'я на
диску випадкове (uuid4) -- ім'я від тренера в шлях не потрапляє ніколи.

Порядок запису: файл -> рядок (flush). Коміт робить маршрут; якщо він
падає, маршрут кличе `discard_file`, інакше на диску лишився б файл без
рядка, якого ніхто ніколи не знайде.
"""
import logging
import os
import uuid
from pathlib import Path

from flask import current_app

from app.extensions import db
from app.models.trainer_presentation import TrainerPresentation
from app.utils import truncate_filename

logger = logging.getLogger(__name__)

# Розширення -> (MIME, допустимі сигнатури). PPTX, KEY і ODP -- ZIP-архіви,
# PPT -- контейнер OLE2. Сигнатура звіряється з першими байтами файлу.
_ZIP = (b'PK\x03\x04',)
FORMATS = {
    'pdf': ('application/pdf', (b'%PDF-',)),
    'pptx': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', _ZIP),
    'ppt': ('application/vnd.ms-powerpoint', (bytes.fromhex('D0CF11E0A1B11AE1'),)),
    'key': ('application/vnd.apple.keynote', _ZIP),
    'odp': ('application/vnd.oasis.opendocument.presentation', _ZIP),
}
ACCEPT_ATTR = ','.join('.' + ext for ext in FORMATS)

# Хто отримує лист про нову презентацію. Саме ролі, а не право
# notifications.receive: редактор контенту його не має, а готує захід саме
# він (узгоджено 24.09.2026).
RECIPIENT_ROLES = ('super_admin', 'admin', 'content_editor')

_CHUNK = 1024 * 1024


def folder():
    return Path(current_app.config['TRAINER_PRESENTATION_FOLDER'])


def file_path(presentation):
    return folder() / str(presentation.instance_id) / presentation.stored_name


def max_bytes():
    return int(current_app.config['TRAINER_PRESENTATION_MAX_BYTES'])


def max_mb():
    return max_bytes() // (1024 * 1024)


def _extension(filename):
    name = (filename or '').strip()
    if '.' not in name:
        return ''
    return name.rsplit('.', 1)[1].lower()


def save_upload(trainer, instance, file_storage, uploader):
    """Перевірити й записати файл, додати рядок у сесію (flush, без коміту).

    Повертає (presentation, None) або (None, текст помилки для тренера).
    """
    from flask_babel import gettext as _

    if file_storage is None or not file_storage.filename:
        return None, _('Оберіть файл презентації.')
    ext = _extension(file_storage.filename)
    if ext not in FORMATS:
        return None, _('Дозволені формати: PDF, PPTX, PPT, KEY, ODP.')
    mimetype, signatures = FORMATS[ext]

    stream = file_storage.stream
    head = stream.read(16)
    if not head:
        return None, _('Файл порожній.')
    if not any(head.startswith(sig) for sig in signatures):
        return None, _('Вміст файлу не відповідає його розширенню.')

    limit = max_bytes()
    target_dir = folder() / str(instance.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f'{uuid.uuid4().hex}.{ext}'
    target = target_dir / stored_name
    partial = target_dir / (stored_name + '.part')
    size = 0
    try:
        with open(partial, 'wb') as out:
            chunk = head
            while chunk:
                size += len(chunk)
                if size > limit:
                    raise _TooLarge()
                out.write(chunk)
                chunk = stream.read(_CHUNK)
        os.replace(partial, target)
    except _TooLarge:
        partial.unlink(missing_ok=True)
        return None, _('Файл завеликий: не більше %(mb)d МБ.', mb=max_mb())
    except OSError:
        partial.unlink(missing_ok=True)
        logger.exception('Failed to write trainer presentation for instance %s', instance.id)
        return None, _('Не вдалося зберегти файл. Спробуйте ще раз.')

    original = truncate_filename(file_storage.filename) or stored_name
    presentation = TrainerPresentation(
        trainer_id=trainer.id, instance_id=instance.id,
        original_filename=original, stored_name=stored_name,
        mimetype=mimetype, size_bytes=size,
        uploaded_by_id=uploader.id if uploader is not None else None,
    )
    db.session.add(presentation)
    db.session.flush()
    return presentation, None


class _TooLarge(Exception):
    pass


def discard_file(presentation):
    """Прибрати файл, чий рядок не закомітився."""
    try:
        file_path(presentation).unlink(missing_ok=True)
    except OSError:
        logger.exception('Failed to discard presentation file %s', presentation.stored_name)


def delete(presentation):
    """Видалити рядок і файл. Файл -- ПІСЛЯ коміту: відкат рядка не має
    лишити рядок без файлу."""
    path = file_path(presentation)
    db.session.delete(presentation)
    db.session.commit()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception('Failed to remove presentation file %s', path)


def for_trainer(trainer, instance_ids):
    """{instance_id: [презентації тренера, від нових]} одним запитом."""
    if not instance_ids:
        return {}
    rows = (TrainerPresentation.query
            .filter(TrainerPresentation.trainer_id == trainer.id,
                    TrainerPresentation.instance_id.in_(list(instance_ids)))
            .order_by(TrainerPresentation.created_at.desc(), TrainerPresentation.id.desc())
            .all())
    grouped = {}
    for row in rows:
        grouped.setdefault(row.instance_id, []).append(row)
    return grouped


def for_instance(instance_id):
    """Усі презентації заходу (усіх тренерів) -- для адмінки."""
    return (TrainerPresentation.query
            .filter_by(instance_id=instance_id)
            .order_by(TrainerPresentation.created_at.desc(), TrainerPresentation.id.desc())
            .all())


def recipient_emails():
    """Адреси активних співробітників із ролями RECIPIENT_ROLES, без дублів."""
    from app.models.rbac import Role
    from app.models.user import User

    users = (User.query
             .filter(User.is_active.is_(True))
             .filter(User.roles.any(Role.name.in_(RECIPIENT_ROLES)))
             .order_by(User.id)
             .all())
    seen, emails = set(), []
    for user in users:
        email = (user.email or '').strip()
        if email and email.lower() not in seen:
            seen.add(email.lower())
            emails.append(email)
    return emails
