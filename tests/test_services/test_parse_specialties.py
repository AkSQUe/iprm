"""problems() -- сторож, який має ловити обірваний хвіст підрозділу.

Стара версія скидала лічильник очікуваного номера щоразу, коли бачила
число 1, незалежно від того, чи справді перед записом стояв заголовок
розділу/підрозділу. Через це рядок-сміття з номером "1" (наприклад, шапка
таблиці частини 2 Додатка, що прорвалась крізь `parse()`) маскувався під
легітимний початок нового підрозділу і не потрапляв у список зауважень --
фантомний запис "specialists #29" знайшовся лише ручним перерахунком
підрозділів, а не цією перевіркою.

Фікс: parse() тепер несе прапорець after_header у кожному записі (перед
ним щойно був заголовок розділу чи підрозділу), і problems() скидає
очікуваний номер на 1 лише за цим прапорцем, а не за самим значенням
номера.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))

import parse_specialties as ps  # noqa: E402

# Використовуємо СПРАВЖНІй кириличний символ розділу з SECTIONS модуля, а не
# вручну набраний -- 'І' (укр.) і латинська 'I' виглядають однаково, але це
# різні символи, і _SECTION_RE впізнає лише перший.
_SECTION_HEAD = next(iter(ps.SECTIONS))


def test_problems_direct_legitimate_restart_after_header_is_clean():
    """Рестарт нумерації з 1 ПІСЛЯ заголовка підрозділу -- це не зауваження."""
    entries = [
        ('medical', 1, 'Перша', True),
        ('medical', 2, 'Друга', False),
        ('medical', 1, 'Третя', True),   # новий підрозділ -- легітимний рестарт
        ('medical', 2, 'Четверта', False),
    ]
    assert ps.problems(entries) == []


def test_problems_direct_restart_without_header_is_flagged():
    """Номер 1 БЕЗ заголовка перед ним -- підозра на обірваний хвіст, а не
    новий підрозділ. Так виглядав би пропущений фантомний рядок-сміття,
    якби він мав номер 1 і опинився в середині розділу без заголовка.
    """
    entries = [
        ('specialists', 1, 'Перша', True),
        ('specialists', 2, 'Друга', False),
        ('specialists', 3, 'Третя', False),
        ('specialists', 1, 'Сміття', False),   # немає заголовка -- не рестарт
    ]
    found = ps.problems(entries)
    assert len(found) == 1
    assert 'очікував номер 4, отримав 1' in found[0]


def test_problems_direct_gap_inside_subsection_is_flagged():
    """Дірка всередині підрозділу (без будь-якого заголовка між сусідніми
    номерами) -- завжди зауваження, незалежно від after_header-фікса.
    """
    entries = [
        ('pharmacy', 1, 'Перша', True),
        ('pharmacy', 3, 'Третя', False),   # пропущено номер 2
    ]
    found = ps.problems(entries)
    assert len(found) == 1
    assert 'очікував номер 2, отримав 3' in found[0]


# --- те саме через справжній parse(), щоб перевірити, що after_header ------
# справді доходить від заголовків до problems(), а не тільки в синтетичних
# кортежах вище.

def test_parse_then_problems_clean_on_legitimate_subsection_restart():
    lines = [
        f'{_SECTION_HEAD}. РОЗДІЛ ТЕСТОВИЙ',
        '1. Підрозділ А',
        '1 Перша спеціальність',
        '2 Друга спеціальність',
        '2. Підрозділ Б',
        '1 Третя спеціальність',
    ]
    entries = ps.parse(lines)
    assert ps.problems(entries) == []


def test_parse_then_problems_catches_restart_without_header():
    """Без рядка-заголовка між підрозділами номер "1" не має права
    скидати лічильник -- рівно та ситуація, яку раніше маскував старий код.
    """
    lines = [
        f'{_SECTION_HEAD}. РОЗДІЛ ТЕСТОВИЙ',
        '1. Підрозділ А',
        '1 Перша спеціальність',
        '2 Друга спеціальність',
        '3 Третя спеціальність',
        '1 Сміття без заголовка',
    ]
    entries = ps.parse(lines)
    found = ps.problems(entries)
    assert len(found) == 1
    assert 'очікував номер 4, отримав 1' in found[0]
