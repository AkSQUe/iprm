"""Тести .ics-вкладення та посилання "додати в Google Calendar".

Подія в календарі учасника -- головний засіб проти неявки, тому важливі
саме нудні речі: правильний зсув часу, екранування спецсимволів і
складання довгих рядків (кирилична назва курсу легко вилазить за 75
октетів, а невідповідний .ics поштові клієнти просто мовчки ігнорують).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import calendar_service as cs


class _Event:
    title = 'PRP-терапія: сучасні протоколи'
    slug = 'prp'
    start_date = datetime(2026, 8, 15, 11, 0, tzinfo=timezone(timedelta(hours=3)))
    end_date = None
    location = 'Київ, вул. Хрещатик, 1; каб. 5'
    online_link = ''


class _Registration:
    id = 42


BASE = 'https://plasma-regen.com'


def _ics_text(event=None, registration=None):
    data = cs.build_ics(event or _Event(), registration or _Registration(),
                        base_url=BASE)
    return data.decode('utf-8')


def _unfold(text):
    """Зібрати складені рядки назад (продовження починається з пробілу)."""
    return text.replace('\r\n ', '')


def test_no_start_date_gives_no_attachment():
    """Чернетка без дати -- не помилка: лист має піти без вкладення."""
    class _NoDate(_Event):
        start_date = None

    assert cs.build_ics(_NoDate(), _Registration(), base_url=BASE) is None
    assert cs.ics_attachment(_NoDate(), _Registration(), base_url=BASE) is None
    assert cs.google_calendar_url(_NoDate(), base_url=BASE) is None


def test_datetime_is_converted_to_utc():
    """11:00 за київським часом -- це 08:00Z, а не 11:00Z."""
    text = _ics_text()
    assert 'DTSTART:20260815T080000Z' in text


def test_missing_end_date_falls_back_to_default_duration():
    text = _ics_text()
    assert 'DTEND:20260815T110000Z' in text  # +3 години


def test_explicit_end_date_wins():
    class _WithEnd(_Event):
        end_date = datetime(2026, 8, 15, 18, 0, tzinfo=timezone.utc)

    assert 'DTEND:20260815T180000Z' in _ics_text(_WithEnd())


def test_text_values_are_escaped():
    """Кома і крапка з комою в адресі розірвали б значення LOCATION."""
    text = _unfold(_ics_text())
    assert r'LOCATION:Київ\, вул. Хрещатик\, 1\; каб. 5' in text


def test_lines_fit_the_octet_limit():
    """RFC 5545: не більше 75 октетів у рядку -- рахуємо байти, не символи."""
    for line in _ics_text().split('\r\n'):
        assert len(line.encode('utf-8')) <= 75, line


def test_folding_does_not_corrupt_cyrillic():
    """Розрив посеред багатобайтового символу зробив би файл нечитабельним."""
    class _LongTitle(_Event):
        title = 'Терапевтична сила плазми: нові методи в реабілітації та естетиці'

    text = _unfold(_ics_text(_LongTitle()))
    assert f'SUMMARY:{_LongTitle.title}' in text


def test_uid_is_stable_per_registration():
    """Повторний лист має оновити ту саму подію, а не створити другу."""
    assert 'UID:iprm-reg-42@plasma-regen.com' in _ics_text()
    assert _ics_text().count('BEGIN:VEVENT') == 1


def test_uid_without_registration_is_still_deterministic():
    """UID з поточного часу ламав би сам сенс стабільного UID."""
    first = cs.build_ics(_Event(), None, base_url=BASE).decode('utf-8')
    second = cs.build_ics(_Event(), None, base_url=BASE).decode('utf-8')
    uid = 'UID:iprm-prp-20260815T080000Z@plasma-regen.com'
    assert uid in first and uid in second


def test_structure_and_reminder():
    text = _ics_text()
    assert text.startswith('BEGIN:VCALENDAR\r\n')
    assert text.endswith('END:VCALENDAR\r\n')
    assert 'BEGIN:VALARM' in text and 'TRIGGER:-P1D' in text
    assert f'URL:{BASE}/courses/prp' in _unfold(text)


def test_attachment_tuple_shape():
    attachment = cs.ics_attachment(_Event(), _Registration(), base_url=BASE)
    filename, mimetype, data = attachment
    assert filename.endswith('.ics')
    assert mimetype.startswith('text/calendar')
    assert isinstance(data, bytes)


def test_google_calendar_url_carries_utc_window():
    url = cs.google_calendar_url(_Event(), base_url=BASE)
    assert url.startswith(cs.GOOGLE_CALENDAR_BASE)
    assert 'dates=20260815T080000Z%2F20260815T110000Z' in url


@pytest.mark.parametrize('location,online,expected', [
    ('Київ', 'https://zoom.us/j/1', 'Київ'),
    ('', 'https://zoom.us/j/1', 'https://zoom.us/j/1'),
    ('', '', ''),
])
def test_location_falls_back_to_online_link(location, online, expected):
    class _E(_Event):
        pass

    _E.location = location
    _E.online_link = online
    assert cs._location(_E()) == expected
