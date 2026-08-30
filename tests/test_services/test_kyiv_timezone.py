"""Київський час мусить знати про перехід на зимовий.

Раніше зона була записана як фіксований `timezone(timedelta(hours=3))` --
влітку це правда, а з останньої неділі жовтня Київ живе на UTC+2. Наслідок
тихий: підпис часу, межа доби у фільтрі по датах і клітинка xlsx усю зиму
показували годину вперед. Число виглядає правдоподібно, просто не збігається
з годинником читача -- на реєстрі лідів, де сенс сторінки в тому, СКІЛЬКИ
заявка чекає, це прямо псує головну цифру.

Копій константи чотири (`utils`, `_listing`, `xlsx_io`, `participant_service`);
зведення їх в одну -- окрема правка, тож поки перевіряємо всі чотири: розійтись
вони можуть тільки мовчки.
"""
from datetime import datetime, timezone

import pytest

from app.admin._listing import KYIV as KYIV_LISTING
from app.services.participant_service import _KYIV as KYIV_PARTICIPANT
from app.services.xlsx_io import KYIV as KYIV_XLSX
from app.utils import KYIV, to_kyiv

ALL_COPIES = [KYIV, KYIV_LISTING, KYIV_XLSX, KYIV_PARTICIPANT]


@pytest.mark.parametrize('tz', ALL_COPIES)
@pytest.mark.parametrize('month, hours', [(1, 2), (8, 3)])
def test_offset_follows_the_season(tz, month, hours):
    """Січень -- UTC+2, серпень -- UTC+3. Фіксований зсув валить перший."""
    moment = datetime(2026, month, 15, 12, 0, tzinfo=timezone.utc)
    assert moment.astimezone(tz).utcoffset().total_seconds() == hours * 3600


def test_all_copies_agree():
    """Чотири копії -- одна зона. Розбіжність тут не має де проявитись."""
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    assert len({winter.astimezone(tz).isoformat() for tz in ALL_COPIES}) == 1


def test_to_kyiv_converts_winter_moment():
    """Наскрізь через публічний хелпер, яким користуються шаблони."""
    assert to_kyiv(datetime(2026, 1, 15, 22, 30, tzinfo=timezone.utc)).hour == 0
