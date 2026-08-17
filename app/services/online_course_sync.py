"""Синхронізація каталогу онлайн-курсів із Sintegrum.

Тягне повний перелік треків і оновлює дзеркало online_courses. Правила,
які тут важливіші за код:

* оновлюються ЛИШЕ remote_*-поля. Наші slug, тексти, ціна, посилання й
  публікація не чіпаються, інакше кожен прогін затирав би редакторську
  роботу;
* нові курси приходять чернетками (is_published=False). Публікує людина,
  бо для продажу треба ще посилання на навчання і ціну;
* курс, якого не було у видачі, позначається is_vanished, а не видаляється:
  на нього можуть посилатися оплачені замовлення;
* часткова невдача -- не привід нікого ховати. Якщо каталог не витягнувся
  повністю, ми взагалі нічого не позначаємо зниклим, інакше збій мережі
  вимів би з сайту весь розділ.
"""
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.mixins import utcnow
from app.models.online_course import OnlineCourse
from app.models.site_settings import SiteSettings
from app.services.sintegrum_client import SintegrumClient, SintegrumConfigError

logger = logging.getLogger(__name__)

STATUS_OK = 'ok'
STATUS_ERROR = 'error'
STATUS_DISABLED = 'disabled'


@dataclass
class SyncReport:
    status: str = STATUS_OK
    created: int = 0
    updated: int = 0
    vanished: int = 0
    restored: int = 0
    covers: int = 0
    error: str = ''
    skipped: list = field(default_factory=list)

    @property
    def ok(self):
        return self.status == STATUS_OK

    @property
    def summary(self):
        if self.status == STATUS_DISABLED:
            return 'Інтеграцію вимкнено'
        if self.status == STATUS_ERROR:
            return f'Помилка: {self.error}'
        return (
            f'Створено {self.created}, оновлено {self.updated}, '
            f'зникло {self.vanished}, повернулось {self.restored}, '
            f'обкладинок {self.covers}'
        )


def _to_decimal(value):
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_int(value):
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def generate_unique_slug(name, *, exclude_id=None):
    """Унікальний slug із назви курсу (з суфіксом -2, -3 за потреби)."""
    from app.services.blog_service import slugify

    base = slugify(name) or 'kurs'
    candidate = base
    n = 2
    while True:
        query = OnlineCourse.query.filter_by(slug=candidate)
        if exclude_id is not None:
            query = query.filter(OnlineCourse.id != exclude_id)
        if not db.session.query(query.exists()).scalar():
            return candidate
        candidate = f'{base}-{n}'
        n += 1


def _apply_remote_fields(course, payload, now):
    """Записати дані Sintegrum. Повертає True, якщо щось справді змінилось."""
    incoming = {
        'remote_name': (payload.get('name') or '').strip()[:255],
        'remote_description': payload.get('description'),
        'remote_price': _to_decimal(payload.get('price')),
        'remote_status': _to_int(payload.get('status')),
        'remote_parent_id': _to_int(payload.get('parent_id')),
    }

    changed = False
    for attr, value in incoming.items():
        if getattr(course, attr) != value:
            setattr(course, attr, value)
            changed = True

    # Сирий payload оновлюємо завжди: він потрібен для розбору польотів,
    # навіть коли відомі нам поля не змінились.
    if course.remote_payload != payload:
        course.remote_payload = payload
        changed = True

    course.last_seen_at = now
    return changed


def sync_courses(with_covers=True):
    """Один прогін синхронізації. Ніколи не кидає -- повертає SyncReport.

    `with_covers=False` пропускає другий прохід -- завантаження обкладинок.
    Саме він довгий: це HTTP-запит і запис файлу на КОЖЕН курс. У фоновій
    джобі це нормально, а от кнопка в адмінці на ньому підвисає й може
    впертись у таймаут проксі. Каталог після такого прогону повний, бракує
    лише картинок -- їх підбере найближчий плановий прохід.
    """
    settings = SiteSettings.get()
    report = SyncReport()

    try:
        client = SintegrumClient.from_settings(settings)
    except SintegrumConfigError as exc:
        report.status = STATUS_DISABLED
        report.error = str(exc)
        _record_run(settings, report)
        return report

    result = client.list_all_courses()
    if not result.ok:
        report.status = STATUS_ERROR
        report.error = result.error or 'Невідома помилка'
        logger.warning('Sintegrum sync failed: %s', report.error)
        _record_run(settings, report)
        return report

    payloads = result.data if isinstance(result.data, list) else []
    now = utcnow()

    try:
        seen_ids = _upsert(payloads, now, report)
        report.vanished = _mark_vanished(seen_ids, report)
        _record_run(settings, report, commit=False)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        report.status = STATUS_ERROR
        report.error = str(exc)[:500]
        report.created = report.updated = report.vanished = report.restored = 0
        logger.exception('Sintegrum sync failed while writing the mirror')
        _record_run(settings, report)
        return report

    if with_covers:
        _sync_covers(report)

    logger.info('Sintegrum sync: %s', report.summary)
    return report


def _sync_covers(report):
    """Другий прохід: обкладинки з фіду в наш медіа-реєстр.

    Свідомо ПІСЛЯ коміту дзеркала і окремою транзакцією на курс. Дві причини:
    відкат запису дзеркала не має лишати на диску сиротливі файли, а збита
    картинка одного курсу не має ні валити прогін, ні відкочувати сусідів.
    """
    from app.services.online_course_media import sync_cover

    courses = OnlineCourse.query.filter(OnlineCourse.is_vanished.is_(False)).all()
    for course in courses:
        try:
            if sync_cover(course):
                db.session.commit()
                report.covers += 1
        except Exception:
            db.session.rollback()
            logger.exception('Обкладинка курсу %s: не вдалося зберегти',
                             course.sintegrum_id)


def _upsert(payloads, now, report):
    """Створити/оновити курси. Повертає множину побачених sintegrum_id."""
    seen_ids = set()

    existing = {
        course.sintegrum_id: course
        for course in OnlineCourse.query.all()
    }

    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        sintegrum_id = _to_int(payload.get('id'))
        name = (payload.get('name') or '').strip()
        if sintegrum_id is None or not name:
            # Курс без id або без назви показати нема як -- пропускаємо,
            # але голосно: мовчазна втрата запису гірша за шум у логах.
            report.skipped.append(payload.get('id'))
            logger.warning('Sintegrum: пропущено курс без id або назви: %r', payload)
            continue

        seen_ids.add(sintegrum_id)
        course = existing.get(sintegrum_id)

        if course is None:
            course = OnlineCourse(
                sintegrum_id=sintegrum_id,
                remote_name=name[:255],
                slug=generate_unique_slug(name),
                first_seen_at=now,
                is_published=False,
            )
            _apply_remote_fields(course, payload, now)
            db.session.add(course)
            # Наступні курси в цьому ж прогоні мають бачити зайнятий slug.
            db.session.flush()
            existing[sintegrum_id] = course
            report.created += 1
            continue

        changed = _apply_remote_fields(course, payload, now)
        if course.is_vanished:
            # Курс повернувся у видачу. Публікацію не вмикаємо самі:
            # її зняли (чи не вмикали) люди, їм і вирішувати.
            course.is_vanished = False
            report.restored += 1
        elif changed:
            report.updated += 1

    return seen_ids


def _mark_vanished(seen_ids, report):
    """Позначити зниклими тих, кого не було у видачі."""
    if not seen_ids:
        # Порожній каталог технічно можливий, але майже завжди означає
        # проблему на тому боці. Ховати весь розділ через це не станемо.
        logger.warning('Sintegrum: видача порожня, нікого не позначаємо зниклим')
        return 0

    vanished = 0
    stale = OnlineCourse.query.filter(
        ~OnlineCourse.sintegrum_id.in_(seen_ids),
        OnlineCourse.is_vanished.is_(False),
    ).all()
    for course in stale:
        course.is_vanished = True
        vanished += 1
        logger.info(
            'Sintegrum: курс %s (%s) зник із видачі',
            course.sintegrum_id, course.remote_name,
        )
    return vanished


def _record_run(settings, report, commit=True):
    settings.sintegrum_last_sync_at = utcnow()
    settings.sintegrum_last_sync_status = report.status
    settings.sintegrum_last_sync_error = report.error or ''
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Не вдалося зберегти результат прогону синхронізації')
