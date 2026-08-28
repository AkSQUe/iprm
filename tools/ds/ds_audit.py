#!/usr/bin/env python
"""Числа концепту "дизайн-система -- джерело істини".

Відповідає на чотири питання:
  1. які CSS-файли компонентні, а які посторінкові (і скільки в кого споживачів);
  2. які класи оголошені більш ніж в одному файлі -- саме там правка
     дизайн-системи до сторінки НЕ доходить;
  3. які компонентні файли не підключені до каталогу;
  4. чиє ім'я суперечить суті (page-* у компонента і навпаки).

Межа: файл компонентний, якщо має 2+ шаблони-споживачі. Споживачі
рахуються ТРАНЗИТИВНО -- через extends і include: CSS із партіала має
одного прямого споживача (сам партіал), хоча партіал інклюдять десятки
сторінок.

Клас вважається ОГОЛОШЕНИМ у файлі лише тоді, коли він стоїть у СУБ'ЄКТІ
правила -- останній компаунд селектора, після всіх комбінаторів (пробіл,
`>`, `+`, `~`) і поза аргументами :not()/:has()/:is()/:where(). Згадка
класу як предка (`.card .badge` -- предок `.card`) чи як цілі `:has()`
нічого не перестилізовує, тож дублікатом не рахується: правку компонента
в дизайн-системі така згадка "не ловить" помилково.

Використання:
    python tools/ds/ds_audit.py                # повний звіт
    python tools/ds/ds_audit.py --write-baseline
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'tests' / 'test_design_system' / 'duplicate_classes_baseline.json'

# Шаблон каталогу ПОКАЗУЄ компоненти, а не вживає їх: інакше кожен показаний
# клас робив би свій файл компонентним сам собою.
CATALOG_GLOBS = ('design_system/*.html', 'admin/design_system*.html')

_EXTENDS = re.compile(r"{%-?\s*extends\s+['\"]([^'\"]+)['\"]")
_INCLUDE = re.compile(r"{%-?\s*include\s+['\"]([^'\"]+)['\"]")
_INCLUDE_DYNAMIC = re.compile(r"{%-?\s*include\s+(?!['\"])")
# Дві форми <link>, якими шаблон підключає CSS -- обидві валідні за
# правилами проєкту (кожен <link> несе ?v={{ assets_version }}, а ЯК саме
# побудований href -- не regламентовано):
#   1. href="{{ url_for('static', filename='css/x.css') }}?v=..." -- ловить
#      перша частина, на буквальному `filename=`;
#   2. href="/static/css/x.css?v={{ assets_version }}" -- літеральний шлях
#      без url_for; ловить друга частина, на буквальному `static/css/`.
# Файл, підключений лише другою формою, для першої версії regexp був
# невидимий: classify_css рахував 0 споживачів, catalog_gap його не бачив
# узагалі, і 91 тест лишався зеленим.
_CSS_LINK = re.compile(
    r"filename=['\"]css/([\w.-]+\.css)['\"]"
    r"|href=['\"][^'\"]*?static/css/([\w.-]+\.css)"
)
_COMMENT = re.compile(r'/\*.*?\*/', re.S)

# Розбір суб'єкта селектора (той компаунд, який правило РЕАЛЬНО стилізує):
# _PAREN викидає аргументи функціональних псевдокласів (:not(), :has(),
# :is(), :where(), :nth-child() тощо) -- клас усередині нічого не
# перестилізовує, він лише умова відбору; _BRACKET так само викидає вміст
# атрибутних селекторів (там трапляються `>`/`+`/`~`, які інакше сплутати
# з комбінаторами); _COMBINATOR ділить те, що лишилось, на компаунди --
# суб'єкт це ОСТАННІЙ компаунд.
_PAREN = re.compile(r'\([^()]*\)')
_BRACKET = re.compile(r'\[[^\[\]]*\]')
_COMBINATOR = re.compile(r'[\s>+~]+')


def _templates(root):
    tpl = root / 'app' / 'templates'
    return {
        p.relative_to(tpl).as_posix(): p.read_text(encoding='utf-8', errors='ignore')
        for p in tpl.rglob('*.html')
    }


def _catalog_names(root):
    tpl = root / 'app' / 'templates'
    names = set()
    for pattern in CATALOG_GLOBS:
        for p in tpl.glob(pattern):
            names.add(p.relative_to(tpl).as_posix())
    return names


def _css_links(text):
    """Імена CSS-файлів, підключених у `text` -- обидві форми `<link>`
    (`filename='css/...'` через `url_for` і буквальний `static/css/...`).
    `_CSS_LINK` має два групи захоплення, по одній на форму -- у кожному
    збігу рівно одна з них непорожня.
    """
    return {a or b for a, b in _CSS_LINK.findall(text)}


def _link_graph(texts):
    """(direct, parents) для графа шаблонів `texts` (ім'я -> вміст).

    `direct[name]` -- CSS, підключений У ЦЬОМУ файлі напряму (обидві форми
    `<link>` -- див. `_css_links`). `parents[name]` -- файли, які `name`
    розширює чи інклюдить (`extends`/`include`), лише ті, що реально є в
    `texts`. Разом -- граф, яким рекурсивно ходить `_effective_css`.
    """
    direct = {name: _css_links(text) for name, text in texts.items()}
    parents = {}
    for name, text in texts.items():
        refs = set(_EXTENDS.findall(text)) | set(_INCLUDE.findall(text))
        parents[name] = {r for r in refs if r in texts}
    return direct, parents


def _effective_css(name, direct, parents, seen=None):
    """CSS, транзитивно підключений при рендері шаблону `name`.

    Це сам файл плюс усе, що він extends/include, рекурсивно, БЕЗ
    обмеження глибини -- партіал у партіалі у партіалі так само
    враховується, як і прямий include. `seen` захищає від циклів у
    графі extends/include.

    Єдина реалізація обходу графа: і `classify_css` (споживачі шаблону),
    і `catalog_gap` (що підключає сторінка каталогу) мусять користуватись
    саме нею, а не власним розгортанням на N рівнів -- бо ручне
    розгортання на фіксовану глибину мовчки недораховує все, що глибше.
    """
    seen = seen if seen is not None else set()
    if name in seen:
        return set()
    seen.add(name)
    out = set(direct.get(name, ()))
    for parent in parents.get(name, ()):
        out |= _effective_css(parent, direct, parents, seen)
    return out


def classify_css(root=ROOT):
    """{'component': {файл: споживачів}, 'page': {...}, 'unresolved': [...]}"""
    texts = _templates(root)
    catalog = _catalog_names(root)
    direct, parents = _link_graph(texts)

    unresolved = [n for n, t in texts.items() if _INCLUDE_DYNAMIC.search(t)]

    counts = {}
    for name in texts:
        if name in catalog:
            continue
        for css in _effective_css(name, direct, parents):
            counts[css] = counts.get(css, 0) + 1

    for css_file in (root / 'app' / 'static' / 'css').glob('*.css'):
        counts.setdefault(css_file.name, 0)

    component = {k: v for k, v in sorted(counts.items()) if v > 1}
    page = {k: v for k, v in sorted(counts.items()) if v <= 1}
    return {'component': component, 'page': page, 'unresolved': sorted(unresolved)}


def _strip_nested(text, pattern):
    """Прибрати вміст дужок/квадратних дужок навіть при вкладеності.

    Одного проходу regex недостатньо для `:not(:is(.a, .b))` -- внутрішні
    дужки лишаться. Проганяємо, доки текст перестає мінятись.
    """
    prev = None
    while prev != text:
        prev = text
        text = pattern.sub('', text)
    return text


def _selector_subject_classes(head):
    """Класи, які СЕЛЕКТОР(и) з `head` реально оголошують -- суб'єкт
    правила, а не предок у descendant-селекторі й не аргумент
    :not()/:has()/:is()/:where().

    `head` -- усе, що стоїть перед `{` (може містити список селекторів
    через кому). Суб'єкт кожного селектора зі списку -- його ОСТАННІЙ
    компаунд після розбиття на комбінатори (пробіл, `>`, `+`, `~`), уже
    без вмісту дужок і атрибутних селекторів. Компаунд може містити
    кілька класів (`.card.card--wide`) -- тоді суб'єкт усі вони.
    """
    stripped = _strip_nested(head, _PAREN)
    stripped = _strip_nested(stripped, _BRACKET)
    names = set()
    for selector in stripped.split(','):
        compounds = [c for c in _COMBINATOR.split(selector.strip()) if c]
        if not compounds:
            continue
        names |= set(re.findall(r'\.([a-zA-Z][\w-]*)', compounds[-1]))
    return names


def _declared_classes(path):
    css = _COMMENT.sub(' ', path.read_text(encoding='utf-8'))
    names = set()
    for head in re.findall(r'([^{}]+)\{', css):
        if head.lstrip().startswith('@'):
            continue
        names |= _selector_subject_classes(head)
    return names


def duplicate_classes(root=ROOT):
    """{клас: [файли]} для класів, оголошених у 2+ файлах."""
    owners = {}
    # rglob, а не glob: підкаталогів у app/static/css сьогодні немає, але
    # тиха діра (файл у підкаталозі мовчки випадає з підрахунку) нічого не
    # коштує закрити наперед. path.name лишається базовим ім'ям -- ключі
    # baseline не зміняться, навіть якщо підкаталоги колись з'являться.
    for path in sorted((root / 'app' / 'static' / 'css').rglob('*.css')):
        for cls in _declared_classes(path):
            owners.setdefault(cls, set()).add(path.name)
    return {c: sorted(f) for c, f in sorted(owners.items()) if len(f) > 1}


def new_duplicate_owners(current, baseline):
    """{клас: [нові власники]} -- те, чого немає в `baseline` для цього класу.

    Порівняння МНОЖИН ІМЕН класів (`set(current) - set(baseline)`) ловить
    лише 70-й новий клас; храповик мусить ловити й обмін власника
    всередині наявного класу з двома власниками ("прибрав один -- завів
    інший"), тому звіряється саме ЦЕЙ словник -- окремо для кожного класу,
    що вже є в baseline чи новий цілком.
    """
    result = {}
    for cls, files in current.items():
        added = sorted(set(files) - set(baseline.get(cls, [])))
        if added:
            result[cls] = added
    return result


def catalog_gap(root=ROOT):
    """Компонентні файли, яких каталог не підключає."""
    texts = _templates(root)
    direct, parents = _link_graph(texts)
    linked = set()
    for name in _catalog_names(root):
        linked |= _effective_css(name, direct, parents)
    return sorted(set(classify_css(root)['component']) - linked)


def naming_mismatch(root=ROOT):
    result = classify_css(root)
    return {
        'should_lose_prefix': sorted(n for n in result['component'] if n.startswith('page-')),
        'should_gain_prefix': sorted(
            n for n in result['page']
            if not n.startswith('page-') and result['page'][n] == 1
        ),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--write-baseline', action='store_true',
                    help='перезаписати baseline дублікатів (лише коли він ЗМЕНШУЄТЬСЯ)')
    args = ap.parse_args()

    kinds = classify_css()
    dupes = duplicate_classes()
    gap = catalog_gap()
    naming = naming_mismatch()

    print('КОМПОНЕНТНИХ ФАЙЛІВ: %d' % len(kinds['component']))
    print('ПОСТОРІНКОВИХ:       %d' % len(kinds['page']))
    if kinds['unresolved']:
        print('  УВАГА: динамічний include у %d шаблонах, споживачі недораховані: %s'
              % (len(kinds['unresolved']), ', '.join(kinds['unresolved'][:5])))
    print('\nДУБЛІКАТИ (клас у 2+ файлах): %d' % len(dupes))
    for cls, files in list(dupes.items())[:10]:
        print('   .%-28s %s' % (cls, ', '.join(files)))
    if len(dupes) > 10:
        print('   ... ще %d' % (len(dupes) - 10))
    print('\nКОМПОНЕНТНІ ФАЙЛИ ПОЗА КАТАЛОГОМ: %d' % len(gap))
    for name in gap:
        print('   ' + name)
    print('\nІМ\'Я СУПЕРЕЧИТЬ СУТІ: %d'
          % (len(naming['should_lose_prefix']) + len(naming['should_gain_prefix'])))
    for name in naming['should_lose_prefix']:
        print('   %-34s компонентний, але з префіксом page-' % name)
    for name in naming['should_gain_prefix']:
        print('   %-34s посторінковий, але без префікса' % name)

    if args.write_baseline:
        # Перший запуск -- baseline ще не існує, порівнювати нема з чим.
        # Без цієї гілки len(old) завжди був би 0, і будь-яка ненульова
        # кількість дублікатів трактувалась би як "стало більше" -- baseline
        # неможливо було б створити взагалі.
        if BASELINE.exists():
            old = json.loads(BASELINE.read_text(encoding='utf-8'))
            # Не лише "стало більше": обмін "прибрав одного власника -- завів
            # іншого" не змінює len(dupes), але це так само новий дублікат --
            # просто в іншому файлі. new_duplicate_owners ловить обидва
            # випадки: і новий ключ-клас, і нового власника в наявному.
            fresh = new_duplicate_owners(dupes, old)
            if fresh:
                print('\nВІДМОВА: зʼявились нові власники дублікатів:')
                for cls, files in sorted(fresh.items()):
                    print('   .%-28s %s' % (cls, ', '.join(files)))
                print('Baseline фіксує ІСНУЮЧИХ власників кожного класу; новий '
                      'власник -- це новий дублікат, навіть якщо старий зник.')
                return 1
        BASELINE.write_text(
            json.dumps(dupes, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
            encoding='utf-8')
        print('\nbaseline записано: %d класів -> %s' % (len(dupes), BASELINE))
    return 0


if __name__ == '__main__':
    sys.exit(main())
