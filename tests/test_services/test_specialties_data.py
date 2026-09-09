"""Сторож згенерованого файлу номенклатури.

Тест не перевіряє кожну назву -- це робота очей при генерації. Він ловить
те, що ламає довідник мовчки: дублікат коду, чужий розділ, порожню назву,
затеклу в назву кваліфікацію і різке схуднення файлу після перегенерації.

MIN_COUNT -- поріг проти різкого схуднення, а не точна кількість позицій:
фактичний розбір dn_650_16042025_dod_3.pdf дав medical=129, pharmacy=7,
professionals=28, specialists=28 (менше за орієнтовні ~136/9/~29/~33 з
брифу задачі -- це підтверджена реальна кількість у документі, а не
недорозбір: problems() у tools/parse_specialties.py не знайшла жодної
дірки в нумерації жодного підрозділу). Пороги нижче зафіксовані трохи під
реальним числом, а не впритул до нього.

Перевірка "не кваліфікація" -- за МЕЖЕЮ СЛОВА, а не префіксом рядка:
"Фармацевтична косметологія" і "Фармацевтична токсикологія" -- це реальні
й правильно розібрані назви фармацевтичних спеціальностей (розділ
pharmacy, #6-7), які просто починаються з того самого кореня, що й слово
"Фармацевт" -- кваліфікація з колонки 4. Голий startswith('Фармацевт') ловив
би їх як хибне спрацювання.
"""
import re

from app.data.specialties import SPECIALTIES

SECTIONS = {'medical', 'pharmacy', 'professionals', 'specialists'}
MIN_COUNT = {'medical': 100, 'pharmacy': 6, 'professionals': 25, 'specialists': 25}
_LEAKED_QUALIFICATION_RE = re.compile(r'^(?:Лікар|Фармацевт)\b')


def test_codes_are_unique():
    codes = [row[0] for row in SPECIALTIES]
    assert len(codes) == len(set(codes))


def test_codes_fit_column():
    assert all(0 < len(row[0]) <= 60 for row in SPECIALTIES)


def test_sections_are_known():
    assert {row[2] for row in SPECIALTIES} == SECTIONS


def test_names_are_not_empty_and_not_qualifications():
    for code, name, _section, _order in SPECIALTIES:
        assert name.strip(), code
        assert not _LEAKED_QUALIFICATION_RE.match(name), code


def test_each_section_has_expected_volume():
    counts = {}
    for _code, _name, section, _order in SPECIALTIES:
        counts[section] = counts.get(section, 0) + 1
    for section, minimum in MIN_COUNT.items():
        assert counts.get(section, 0) >= minimum, (section, counts.get(section))


def test_sort_order_is_sequential_within_section():
    seen = {}
    for _code, _name, section, order in SPECIALTIES:
        seen.setdefault(section, []).append(order)
    for section, orders in seen.items():
        assert orders == list(range(1, len(orders) + 1)), section
