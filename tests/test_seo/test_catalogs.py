"""Повнота каталогів перекладу.

SEO ru/en тримається на .mo: неперекладений рядок віддає фолбек на
українську, і сторінка мовчки виходить у видачу чужою мовою. Перевіряти
title/description по довжині мало сенсу, поки ніщо не гарантує, що
переклад узагалі є.
"""
from pathlib import Path

from babel.messages.mofile import read_mo
from babel.messages.pofile import read_po

CATALOGS = ('ru', 'en')

# Що робити, коли скомпільований каталог відстав від джерела. Текст один
# на всі три способи провалитись (немає .mo, немає рядка, інше значення),
# бо й лікування одне.
COMPILE_HINT = 'pybabel compile -d app/translations'

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


def _catalog_path(lang, suffix):
    return (
        Path(__file__).resolve().parents[2]
        / 'app' / 'translations' / lang / 'LC_MESSAGES' / f'messages.{suffix}'
    )


def _catalog(lang):
    with open(_catalog_path(lang, 'po'), encoding='utf-8') as fh:
        return read_po(fh)


def _compiled(lang):
    """Скомпільований каталог або None, якщо файлу немає.

    None -- не помилка читання, а окремий випадок зі своїм повідомленням:
    .mo в .gitignore, тож у свіжому клоні його немає ЖОДНОГО, і саме
    текст помилки має сказати новачкові, яку команду виконати. Голий
    FileNotFoundError сказав би лише шлях.
    """
    path = _catalog_path(lang, 'mo')
    if not path.exists():
        return None
    with open(path, 'rb') as fh:
        return read_mo(fh)


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


def test_compiled_catalogs_are_not_stale():
    """.po переклали, .mo не перекомпілювали -- сторінка віддає українську.

    Сусідні перевірки читають .po, а рендер читає .mo, і між ними немає
    нічого, що вимагало б їхнього збігу. Тому каталог із перекладеними
    заголовками проходив зеленим, а /ru/ і /en/ віддавали українську: те
    саме розходження вже одного разу підготувало відправку семи
    перекладених заголовків сторінок, які показувались би українською.
    Небезпечно воно й для самих сторожів -- усі перевірки рендеру в
    tests/test_seo дивляться на .mo, тож на застарілому каталозі вони
    оглядають український текст, вважаючи його російським.

    Напрямок звірки -- від джерела до збірки: кожен непорожній і
    не-fuzzy msgstr із .po мусить бути в .mo з тим самим значенням.
    Fuzzy пропускаємо не з поблажливості, а тому, що pybabel їх сам не
    компілює (без --use-fuzzy), тож вимагати їх у .mo означало б вимагати
    неможливого. Зайві рядки в .mo (msgid, який із .po прибрали) не
    перевіряємо: вони нічому не брешуть -- жоден шаблон їх уже не просить.
    """
    problems = []
    for lang in CATALOGS:
        compiled = _compiled(lang)
        if compiled is None:
            problems.append(
                f'{lang}: скомпільованого каталогу немає взагалі '
                f'({_catalog_path(lang, "mo")})'
            )
            continue
        for message in _catalog(lang):
            if not message.id or not message.string or message.fuzzy:
                continue
            built = compiled.get(message.id, message.context)
            label = _label(message.id)
            if built is None:
                problems.append(f'{lang}: немає у .mo -- {label}')
            elif built.string != message.string:
                problems.append(
                    f'{lang}: значення в .mo інше -- {label}'
                    f'\n      .po: {_label(message.string)}'
                    f'\n      .mo: {_label(built.string)}'
                )
    assert not problems, (
        'Скомпільований каталог відстав від джерела -- сторінка віддасть '
        'українську там, де переклад уже написаний.'
        f'\nЛікується одним: {COMPILE_HINT}\n  ' + '\n  '.join(problems)
    )


def _label(value):
    """Короткий і однаковий підпис для msgid/msgstr, у т.ч. множинних."""
    if isinstance(value, (list, tuple)):
        return ' | '.join(str(v)[:70] for v in value)
    return repr(str(value)[:70])
