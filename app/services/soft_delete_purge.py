"""Остаточне прибирання м'яко видалених записів.

М'яке видалення (SoftDeleteMixin) існує лише заради вікна на відкат: адмін
видаляє без діалогу і має тост "Повернути". Після витримки сенсу тримати
рядок немає -- ця задача видаляє його назавжди, а для медіа ще й файли з
диска. Запускає планувальник щодня о 4:30 (scheduler_service).

Витримка велика навмисно: тост живе секунди, але помилку часто помічають
наступного дня, і доти рядок ще можна дістати з БД руками.
"""
import logging

from datetime import timedelta

from app.extensions import db
from app.models.blog_comment import BlogComment
from app.models.media_file import MediaFile
from app.models.mixins import utcnow
from app.models.review import Review

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30


def purge_expired(retention_days=RETENTION_DAYS):
    """Видалити рядки, позначені deleted_at раніше за витримку.

    Повертає {'reviews': N, 'blog_comments': N, 'media_files': N}.
    """
    cutoff = utcnow() - timedelta(days=retention_days)
    stats = {}

    # Медіа окремо: спершу файли з диска, потім рядок.
    from app.services import media_service
    media_rows = MediaFile.query.filter(
        MediaFile.deleted_at.isnot(None), MediaFile.deleted_at < cutoff,
    ).all()
    for media in media_rows:
        media_service.delete_media(media)   # прибирає файли + db.session.delete
    stats['media_files'] = len(media_rows)

    for model, key in ((Review, 'reviews'), (BlogComment, 'blog_comments')):
        rows = model.query.filter(
            model.deleted_at.isnot(None), model.deleted_at < cutoff,
        ).all()
        for row in rows:
            db.session.delete(row)
        stats[key] = len(rows)

    if any(stats.values()):
        db.session.commit()
    return stats
