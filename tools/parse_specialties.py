"""Розбір Додатка 1 (номенклатура спеціальностей) у app/data/specialties.py.

Запускається РУКАМИ і одноразово:

    ./venv/Scripts/pip.exe install pypdf
    ./venv/Scripts/python.exe tools/parse_specialties.py dn_650_16042025_dod_3.pdf

pypdf у requirements НЕ додається: у рантаймі PDF не читається, довідник
живе в БД.

Парситься лише частина 1 Додатка ("Спеціальності та професійні
кваліфікації"), розділи I-IV. Частина 2 ("Профілі роботи за
спеціальностями") -- не спеціальності, і у виборі для сертифіката вона б
плутала.

Розбирається КОЛОНКА 2 таблиці (назва спеціальності). Колонка 3 -- позначка
"+" або порожньо, колонка 4 -- професійна кваліфікація; обидві відрізаються.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.specialties import specialty_code  # noqa: E402

# Ключ -- кирилична нумерація розділу з документа.
SECTIONS = {
    'І': 'medical',
    'ІІ': 'pharmacy',
    'ІІІ': 'professionals',
    'ІV': 'specialists',
}

# "ІІІ. СПЕЦІАЛЬНОСТІ ПРОФЕСІОНАЛІВ ..." -- заголовок розділу.
_SECTION_RE = re.compile(r'^(І|ІІ|ІІІ|ІV)\.\s+[А-ЯІЇЄҐ]')
# "2. Лікарські спеціальності ..." або "1) Лікарські спеціальності ..."
_SUBSECTION_RE = re.compile(r'^\d+[.)]\s')
# "12 Дитяча ендокринологія + Лікар-ендокринолог дитячий" або просто "3"
# (у широких рядках номер лишається сам на рядку).
_ENTRY_RE = re.compile(r'^(\d+)(?:\s+(.*))?$')
# Колонтитул сторінки і шапка колонок.
_NOISE_RE = re.compile(r'^(\d+\s+Продовження додатка|1 2 3 4$)')
# Межа між колонкою 2 і рештою рядка: " + " або два-плюс пробіли (порожня
# третя колонка дає саме їх).
_COLUMN_BREAK_RE = re.compile(r'\s\+\s|\s{2,}')
# Кваліфікації з колонки 4 -- якщо таке слово опинилось у назві, розбір з'їхав.
# Межі слова обов'язкові: "Фармацевт" без \b ловить і "Фармацевтична
# косметологія" -- законну назву спеціальності, що просто починається на
# той самий корінь.
_QUALIFICATION_WORDS = ('Лікар', 'Фармацевт', 'Професіонал', 'Сестра',
                        'Експерт', 'Фельдшер', 'Акушерка')
_QUALIFICATION_RE = re.compile(
    r'\b(?:' + '|'.join(_QUALIFICATION_WORDS) + r')\b')


def extract_lines(pdf_path):
    from pypdf import PdfReader

    lines = []
    for page in PdfReader(str(pdf_path)).pages:
        lines.extend((page.extract_text() or '').split('\n'))
    return lines


def parse(lines):
    """[(section, number, name, after_header)] у порядку появи в документі.

    after_header -- True, якщо перед записом (з точністю до порожніх рядків
    і рядків-продовжень заголовка) стояв заголовок розділу чи підрозділу.
    Це єдина ознака, за якою problems() може відрізнити легітимний рестарт
    нумерації від обірваного хвоста попереднього підрозділу.
    """
    entries = []
    section = None
    current = None
    after_header = False
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            if current is not None:
                # Порожній рядок усередині запису -- це межа колонок:
                # зберігаємо його як порожній шматок, щоб склейка дала
                # два пробіли й розрив спрацював.
                current[2].append('')
            continue
        if _NOISE_RE.match(stripped):
            continue
        if 'профілі роботи' in stripped.lower():
            # Частина 2 починається заголовком "2. Профілі роботи за
            # спеціальностями ..." -- це арабська нумерація частини (звичайний
            # регістр), а не РИМСЬКА ВЕЛИКИМИ заголовка розділу, тож
            # порівняння регістронезалежне і стоїть раніше за
            # _SECTION_RE/_SUBSECTION_RE: інакше цей рядок проковтнеться як
            # звичайний підрозділ, і "1 2 3 4 5" з шапки таблиці частини 2
            # стане фантомним записом розділу IV.
            break
        head = _SECTION_RE.match(stripped)
        if head:
            section = SECTIONS[head.group(1)]
            current = None
            after_header = True
            continue
        if _SUBSECTION_RE.match(stripped):
            current = None
            after_header = True
            continue
        entry = _ENTRY_RE.match(stripped)
        if entry and section:
            current = [section, int(entry.group(1)), [entry.group(2) or ''], after_header]
            entries.append(current)
            after_header = False
            continue
        if current is not None:
            if raw != raw.lstrip():
                # Один провідний пробіл у НЕобрізаному рядку -- ознака
                # порожньої 3-ї колонки: 2-га колонка щойно скінчилась, і
                # зразу йде 4-та без "+" між ними (напр. розділ
                # "Спеціальності професіоналів судово-медичного профілю").
                # Вставляємо порожній шматок, щоб склейка дала подвійний
                # пробіл і межа колонок спрацювала так само, як порожній
                # рядок у джерелі.
                current[2].append('')
            current[2].append(stripped)
        # Рядок-продовження заголовка (не належить жодному record і не
        # матчить жоден з патернів вище) -- after_header навмисно НЕ
        # скидається: заголовок може розгортатись на кілька фізичних рядків
        # ("ІV. СПЕЦІАЛЬНОСТІ ФАХІВЦІВ ..." + "ТА ВІДПОВІДНІ ЇМ ...").
    return [(section, number, _name_from(chunks), after_head)
            for section, number, chunks, after_head in entries]


def _name_from(chunks):
    """Назва спеціальності зі шматків рядка таблиці."""
    text = ''
    for chunk in chunks:
        if not text:
            text = chunk
        elif text.endswith('-') and not text.endswith(' -'):
            # Перенесене слово: "Протезування-" + "ортезування" -- дефіс
            # приліплений одразу до літери, без пробілу перед ним.
            text += chunk
        else:
            # "Загальна практика -" + "сімейна медицина" -- це НЕ перенос
            # слова, а пробільний дефіс-роздільник ("практика - сімейна"),
            # якому лише не пощастило впасти на межі рядка. Пробіл перед
            # дефісом у "практика -" відрізняє його від "перенесення-".
            text += ' ' + chunk
    name = _COLUMN_BREAK_RE.split(text.strip(), 1)[0]
    return ' '.join(name.split())


def problems(entries):
    """Чому розбору можна не вірити. Порожній список -- можна.

    entries -- [(section, number, name, after_header)], як повертає parse().
    """
    found = []
    expected = 1
    for section, number, name, after_header in entries:
        if after_header:
            # Перед записом був заголовок розділу чи підрозділу -- у
            # номенклатурі це легітимний рестарт нумерації з 1.
            expected = 1
        if number != expected:
            # Без заголовка перед записом номери в підрозділі йдуть
            # 1, 2, 3 ... без дірок. Дірка чи повтор означає, що рядок
            # склеївся з сусіднім або загубився. Число 1 БЕЗ заголовка
            # перед ним -- це НЕ легітимний рестарт, а підозра на обірваний
            # хвіст попереднього підрозділу (саме так один раз проскочив
            # фантомний запис із шапки таблиці частини 2 -- "1 2 3 4 5" мав
            # номер 1 і раніше маскувався під початок нового підрозділу).
            found.append(f'{section}: очікував номер {expected}, отримав {number} ({name!r})')
        expected = number + 1

        if not name:
            found.append(f'{section} #{number}: порожня назва')
        elif len(name) > 120:
            found.append(f'{section} #{number}: підозріло довга назва {name!r}')
        elif _QUALIFICATION_RE.search(name):
            found.append(f'{section} #{number}: у назву затекла кваліфікація {name!r}')
    return found


def to_rows(entries):
    """[(code, name, section, sort_order)] -- рівно те, що йде у файл даних."""
    rows, taken, order = [], set(), {}
    for section, _number, name, _after_header in entries:
        code = specialty_code(name, taken=taken)
        taken.add(code)
        order[section] = order.get(section, 0) + 1
        rows.append((code, name, section, order[section]))
    return rows


def render_module(rows):
    body = '\n'.join(
        f'    ({code!r}, {name!r}, {section!r}, {sort_order}),'
        for code, name, section, sort_order in rows
    )
    return (
        '"""Номенклатура спеціальностей (Додаток 1, розділи I-IV).\n\n'
        'ЗГЕНЕРОВАНО tools/parse_specialties.py з dn_650_16042025_dod_3.pdf.\n'
        'Руками не правити: файл читає лише міграція specialties_20260909,\n'
        'а після неї довідник живе в БД і правиться в /admin/specialties.\n\n'
        'Рядок: (code, назва, розділ, порядок у розділі).\n'
        '"""\n'
        'SPECIALTIES = [\n'
        f'{body}\n'
        ']\n'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--out', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'app' / 'data' / 'specialties.py')
    args = parser.parse_args()

    entries = parse(extract_lines(args.pdf))
    found = problems(entries)
    counts = {}
    for section, _number, _name, _after_header in entries:
        counts[section] = counts.get(section, 0) + 1
    print('Розібрано:', ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    for line in found:
        print('УВАГА:', line)
    if found:
        print(f'Проблем: {len(found)}. Файл НЕ записано.')
        return 1

    args.out.write_text(render_module(to_rows(entries)), encoding='utf-8')
    print(f'Записано {len(entries)} позицій у {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
