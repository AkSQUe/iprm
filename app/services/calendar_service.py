"""Календарні вкладення (.ics) і посилання "додати в Google Calendar".

Навіщо: лист про оплату був глухим кутом -- людина закривала його і
поверталась до курсу лише коли (і якщо) спрацює нагадування. Подія в
календарі учасника працює постійно й помітно знижує неявку.

Формат -- RFC 5545, мінімально достатній VEVENT: усі поля в UTC (жодних
VTIMEZONE), METHOD:PUBLISH (запрошення від імені організатора ми не
надсилаємо -- це вимагало б ORGANIZER/ATTENDEE і сипало б "прийняти/
відхилити" у поштових клієнтах).

Стабільний UID прив'язаний до реєстрації: повторний лист (ретрай, ручна
переcилка) оновить ту саму подію в календарі, а не створить другу.
"""
import logging
from datetime import timedelta, timezone
from urllib.parse import urlencode, urlparse

from app.models.mixins import utcnow
from app.utils import ensure_utc

logger = logging.getLogger(__name__)

# Скільки триває захід, якщо end_date не заповнено. Порожній DTEND за
# стандартом означав би подію тривалістю в нуль -- у календарі вона
# виглядає як мітка без блоку часу.
DEFAULT_DURATION_HOURS = 3

ICS_FILENAME = 'iprm-course.ics'
ICS_MIMETYPE = 'text/calendar; charset=utf-8; method=PUBLISH'

GOOGLE_CALENDAR_BASE = 'https://calendar.google.com/calendar/render'

# Максимум октетів у рядку .ics (RFC 5545 3.1). Довші рядки складаємо.
_FOLD_LIMIT = 74


def _fmt_dt(dt):
    """datetime -> '20260815T110000Z'.

    astimezone, а не лише ensure_utc: у бази дата приходить із власним
    зсувом, і форматувати її з літерою Z без переведення означало б
    зсунути подію в календарі на кілька годин.
    """
    return ensure_utc(dt).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _escape(text):
    """Екранування TEXT-значення (RFC 5545 3.3.11)."""
    if text is None:
        return ''
    out = str(text)
    out = out.replace('\\', '\\\\')
    out = out.replace(';', r'\;').replace(',', r'\,')
    out = out.replace('\r\n', r'\n').replace('\n', r'\n').replace('\r', r'\n')
    return out


def _fold(line):
    """Скласти довгий рядок за октетами UTF-8 (продовження -- з пробілу).

    Ріжемо саме байти, а не символи: кирилиця в UTF-8 дволітерна, і наївне
    складання за довжиною рядка дало б рядки вдвічі довші за ліміт.
    """
    raw = line.encode('utf-8')
    if len(raw) <= _FOLD_LIMIT:
        return line
    chunks = []
    start = 0
    limit = _FOLD_LIMIT
    while start < len(raw):
        end = min(start + limit, len(raw))
        # Не розірвати багатобайтовий символ: відступаємо з continuation-байтів.
        while end > start and end < len(raw) and (raw[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(raw[start:end].decode('utf-8'))
        start = end
        limit = _FOLD_LIMIT - 1  # наступні рядки починаються з пробілу
    return '\r\n '.join(chunks)


def _event_window(event):
    """(start, end) в UTC або (None, None), якщо дати немає."""
    start = ensure_utc(getattr(event, 'start_date', None))
    if start is None:
        return None, None
    end = ensure_utc(getattr(event, 'end_date', None))
    if end is None or end <= start:
        end = start + timedelta(hours=DEFAULT_DURATION_HOURS)
    return start, end


def _course_url(event, base_url=''):
    slug = getattr(event, 'slug', None)
    base = (base_url or '').rstrip('/')
    if not slug or not base:
        return base or ''
    return f'{base}/courses/{slug}'


def _location(event):
    """Де відбувається: адреса або посилання на трансляцію."""
    location = (getattr(event, 'location', None) or '').strip()
    if location:
        return location
    return (getattr(event, 'online_link', None) or '').strip()


def _uid(event, registration, base_url=''):
    """Стабільний UID події.

    Стабільність тут -- увесь сенс: за нею календар оновлює вже додану
    подію замість того, щоб створити другу. Тому навіть без реєстрації
    UID детермінований (slug + дата), а не побудований з поточного часу.
    """
    host = urlparse(base_url or '').hostname or 'iprm.space'
    reg_id = getattr(registration, 'id', None)
    if reg_id:
        return f'iprm-reg-{reg_id}@{host}'
    slug = getattr(event, 'slug', None) or 'course'
    start = ensure_utc(getattr(event, 'start_date', None))
    stamp = start.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ') if start else 'nodate'
    return f'iprm-{slug}-{stamp}@{host}'


def build_ics(event, registration=None, base_url=''):
    """Вміст .ics для заходу (bytes) або None, якщо дати немає.

    None -- нормальний результат, а не помилка: у чернетки проведення дати
    може не бути, і лист має піти без вкладення.
    """
    start, end = _event_window(event)
    if start is None:
        return None

    url = _course_url(event, base_url)
    title = getattr(event, 'title', '') or 'ІПРМ'
    description_parts = [title]
    if url:
        description_parts.append(url)

    event_lines = [
        f'UID:{_uid(event, registration, base_url)}',
        f'DTSTAMP:{_fmt_dt(utcnow())}',
        f'DTSTART:{_fmt_dt(start)}',
        f'DTEND:{_fmt_dt(end)}',
        f'SUMMARY:{_escape(title)}',
        f'DESCRIPTION:{_escape(chr(10).join(description_parts))}',
        'STATUS:CONFIRMED',
        'TRANSP:OPAQUE',
    ]
    location = _location(event)
    if location:
        event_lines.append(f'LOCATION:{_escape(location)}')
    if url:
        event_lines.append(f'URL:{url}')
    # Нагадування за добу: сам сенс вкладення -- щоб про курс не забули.
    event_lines += [
        'BEGIN:VALARM',
        'ACTION:DISPLAY',
        'TRIGGER:-P1D',
        f'DESCRIPTION:{_escape(title)}',
        'END:VALARM',
    ]

    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//IPRM//Courses//UK',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        *event_lines,
        'END:VEVENT',
        'END:VCALENDAR',
    ]

    body = '\r\n'.join(_fold(line) for line in lines) + '\r\n'
    return body.encode('utf-8')


def ics_attachment(event, registration=None, base_url=''):
    """Кортеж для EmailService.send_email(attachments=[...]) або None."""
    data = build_ics(event, registration=registration, base_url=base_url)
    if data is None:
        return None
    return (ICS_FILENAME, ICS_MIMETYPE, data)


def google_calendar_url(event, base_url=''):
    """Посилання "додати в Google Calendar" або None, якщо дати немає.

    Потрібне окремо від .ics: у вебпошті вкладення відкривають рідко, а
    кнопка в один клік -- це і є той перший клік назад до нас.
    """
    start, end = _event_window(event)
    if start is None:
        return None
    url = _course_url(event, base_url)
    details = getattr(event, 'title', '') or ''
    if url:
        details = f'{details}\n{url}' if details else url
    params = {
        'action': 'TEMPLATE',
        'text': getattr(event, 'title', '') or 'ІПРМ',
        'dates': f'{_fmt_dt(start)}/{_fmt_dt(end)}',
        'details': details,
    }
    location = _location(event)
    if location:
        params['location'] = location
    return f'{GOOGLE_CALENDAR_BASE}?{urlencode(params)}'
