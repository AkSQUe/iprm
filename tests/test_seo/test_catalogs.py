"""Повнота каталогів перекладу.

SEO ru/en тримається на .mo: неперекладений рядок віддає фолбек на
українську, і сторінка мовчки виходить у видачу чужою мовою. Перевіряти
title/description по довжині мало сенсу, поки ніщо не гарантує, що
переклад узагалі є.
"""
from pathlib import Path

from babel.messages.pofile import read_po

CATALOGS = ('ru', 'en')

# Рядки, яким переклад свідомо не додається в цьому раунді:
# msgid -> причина. Виняток завжди іменований.
EMPTY_ALLOWLIST = {
    'Тренер підтвердив матеріали': (
        'листи резервування витратних матеріалів (MM Medic) -- окрема '
        'фіча, поза межами цього плану. Її рядки перекладаються разом із '
        'нею, а не мимохідь.'
    ),
    'Тренер відповів на запит матеріалів — перегляньте, чи є коментар': (
        'листи резервування витратних матеріалів (MM Medic) -- окрема '
        'фіча, поза межами цього плану.'
    ),
    'Тренер відкрив підготовлений комплект і підтвердив його — це заявка, '
    'яку подали ви.': (
        'листи резервування витратних матеріалів (MM Medic) -- окрема '
        'фіча, поза межами цього плану.'
    ),
    'Коментаря тренер не залишив — комплект підтверджено без зауважень.': (
        'листи резервування витратних матеріалів (MM Medic) -- окрема '
        'фіча, поза межами цього плану.'
    ),
}


def _catalog(lang):
    path = (
        Path(__file__).resolve().parents[2]
        / 'app' / 'translations' / lang / 'LC_MESSAGES' / 'messages.po'
    )
    with open(path, encoding='utf-8') as fh:
        return read_po(fh)


def test_catalogs_have_no_unexplained_empty_translations():
    """Порожній msgstr = сторінка українською в ru/en видачі."""
    offenders = []
    for lang in CATALOGS:
        for message in _catalog(lang):
            if not message.id or message.string:
                continue
            if str(message.id) in EMPTY_ALLOWLIST:
                continue
            offenders.append(f'{lang}: {str(message.id)[:70]!r}')
    assert not offenders, (
        'Без перекладу (сторінка віддасть українську):\n  '
        + '\n  '.join(offenders)
    )


def test_allowlist_entries_are_still_untranslated():
    """Переклали -- прибери запис. Інакше список бреше, як і всі інші."""
    stale = []
    for lang in CATALOGS:
        by_id = {str(m.id): m for m in _catalog(lang) if m.id}
        for msgid in EMPTY_ALLOWLIST:
            message = by_id.get(msgid)
            if message is None:
                stale.append(f'{lang}: рядка вже немає в каталозі -- {msgid[:50]!r}')
            elif message.string:
                stale.append(f'{lang}: перекладено -- {msgid[:50]!r}')
    assert not stale, 'EMPTY_ALLOWLIST застарів:\n  ' + '\n  '.join(stale)


def test_every_allowlist_entry_has_a_reason():
    empty = [k for k, why in EMPTY_ALLOWLIST.items() if not (why or '').strip()]
    assert not empty, f'Записи без причини: {empty}'


def test_catalogs_have_no_fuzzy_entries():
    """Друга половина повноти -- fuzzy: `pybabel compile` їх пропускає.

    Сама перевірка вже написана і живе там, де їй місце -- поруч із
    рештою сторожів каталогів. Тут вона ВИКЛИКАЄТЬСЯ, а не копіюється:
    ця сюїта мусить ловити обидві причини, з яких переклад не доїжджає в
    прод, але другого джерела правди про fuzzy в репозиторії бути не має.
    """
    from tests.test_i18n.test_translation_hardening import (
        test_catalogs_have_no_fuzzy_entries as guard,
    )

    guard()
