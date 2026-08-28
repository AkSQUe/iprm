"""ds_audit рахує споживачів CSS транзитивно -- через include і extends.

Наївний підрахунок дає хибний результат: material-symbols.css підключений
з partials/_icon_font.html, тобто прямих споживачів у нього один, хоча
партіал інклюдить base_admin.html, який розширюють усі сторінки адмінки.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'ds'))

import ds_audit


def test_css_from_partial_counts_transitively():
    result = ds_audit.classify_css(ROOT)
    assert 'material-symbols.css' in result['component'], (
        'material-symbols.css підключений з partials/_icon_font.html, який '
        'інклюдить admin/base_admin.html -- це компонентний файл, а не '
        'посторінковий. Схоже, підрахунок споживачів не транзитивний.'
    )
    assert result['component']['material-symbols.css'] > 1


# _CSS_LINK раніше знав лише форму `filename='css/x.css'` (url_for).
# Форма `href="/static/css/x.css?v={{ assets_version }}"` -- літеральний
# шлях без url_for -- так само валідна за правилами проєкту (кожен <link>
# несе ?v=, а ЯК побудований href -- не регламентовано), але для старого
# regexp була невидимою: файл, підключений лише так, давав 0 споживачів у
# classify_css і взагалі не згадувався в catalog_gap.

def test_css_link_recognizes_url_for_and_literal_href_forms(tmp_path):
    """Синтетичне доведення: два шаблони підключають ОДИН файл -- один
    формою url_for, інший буквальним href -- разом мають дати компонентний
    файл із 2 споживачами, а не 0 чи 1.
    """
    tpl_dir = tmp_path / 'app' / 'templates'
    tpl_dir.mkdir(parents=True)
    (tpl_dir / 'via_url_for.html').write_text(
        '<link rel="stylesheet" href="{{ url_for(\'static\', '
        'filename=\'css/shared-widget.css\') }}?v={{ assets_version }}">\n',
        encoding='utf-8')
    (tpl_dir / 'via_literal_href.html').write_text(
        '<link rel="stylesheet" href="/static/css/shared-widget.css'
        '?v={{ assets_version }}">\n',
        encoding='utf-8')
    css_dir = tmp_path / 'app' / 'static' / 'css'
    css_dir.mkdir(parents=True)
    (css_dir / 'shared-widget.css').write_text('.widget { color: red; }', encoding='utf-8')

    result = ds_audit.classify_css(tmp_path)
    assert 'shared-widget.css' in result['component'], (
        'shared-widget.css підключений двома шаблонами -- один через '
        'url_for, інший буквальним href="/static/css/...". Обидві форми '
        'мають рахуватись як підключення.'
    )
    assert result['component']['shared-widget.css'] == 2


def test_css_files_have_no_unrecognized_zero_consumers():
    """Нуль споживачів у classify_css означає, що підключення НЕ
    розпізнане regexp-ом, а не "файл нікому не потрібен" -- єдиний
    легітимний нуль сьогодні належить chrome самого каталогу
    (page-admin-design-system.css: каталог виключений з підрахунку
    споживачів навмисно, бо він ПОКАЗУЄ компоненти, а не вживає їх).
    Будь-який інший нуль -- підозра на нерозпізнану форму <link>.
    """
    result = ds_audit.classify_css(ROOT)
    zero = sorted(name for name, count in result['page'].items() if count == 0)
    assert zero == ['page-admin-design-system.css'], (
        'CSS-файли з 0 розпізнаними споживачами: ' + ', '.join(zero)
        + '\nЯкщо файл справді підключений -- перевірте форму <link>: '
          'можливо, _CSS_LINK у tools/ds/ds_audit.py не впізнає її.'
    )


# Наступні два тести раніше пришпилювали механізм на ЖИВИХ фактах проєкту
# (page-contact.css -- один споживач, apple-btn -- дублікат): `apple-btn`
# -- перша ціль Етапу 2, і в день, коли його зведуть в один файл, пришпилений
# тест почервоніє, хоча концепт саме тоді нарешті виконано. Синтетичні дані
# перевіряють той самий механізм незалежно від того, що зараз лежить у
# app/static/css і app/templates.

def test_page_only_css_declared_by_one_template_is_page(tmp_path):
    """classify_css кладе файл у 'page', коли в нього рівно один споживач."""
    tpl_dir = tmp_path / 'app' / 'templates'
    tpl_dir.mkdir(parents=True)
    (tpl_dir / 'solo.html').write_text(
        '<link rel="stylesheet" href="{{ url_for(\'static\', '
        'filename=\'css/only-here.css\') }}">\n',
        encoding='utf-8')
    css_dir = tmp_path / 'app' / 'static' / 'css'
    css_dir.mkdir(parents=True)
    (css_dir / 'only-here.css').write_text('.solo { color: red; }', encoding='utf-8')

    result = ds_audit.classify_css(tmp_path)
    assert 'only-here.css' in result['page']
    assert result['page']['only-here.css'] == 1


def test_duplicate_classes_detects_class_declared_in_two_files(tmp_path):
    """duplicate_classes ловить клас, суб'єктом якого він є у двох файлах --
    саме той механізм, що не дає правці компонента в дизайн-системі дійти
    до сторінки, яка переоголосила його в себе.
    """
    css_dir = tmp_path / 'app' / 'static' / 'css'
    css_dir.mkdir(parents=True)
    (css_dir / 'common.css').write_text('.shared-btn { color: red; }', encoding='utf-8')
    (css_dir / 'page-demo.css').write_text('.shared-btn { color: blue; }', encoding='utf-8')

    dupes = ds_audit.duplicate_classes(tmp_path)
    assert 'shared-btn' in dupes, (
        '.shared-btn оголошений суб\'єктом у common.css І page-demo.css -- '
        'це і є дублікат, який метрика мусить зловити.'
    )
    assert dupes['shared-btn'] == ['common.css', 'page-demo.css']


# naming_mismatch -- четверте число концепту, і єдине з чотирьох без
# сторожа: Задача 6 звела його до нуля руками, а `git grep naming_mismatch`
# показує, що це ім'я не імпортує жоден тест і жоден інший інструмент --
# лише сам ds_audit.py і README. Нічого не заважає 21-му файлу знову
# збрехати про свою суть (page-* у компонента чи навпаки).

def test_naming_matches_component_boundary():
    """Реальний стан проєкту: обидва списки порожні. Якщо colись зʼявиться
    легітимний виняток (наприклад, chrome каталогу -- сам каталог не
    рахує себе споживачем, тож `page-admin-design-system.css` лишається
    'page' з нулем споживачів і не потрапляє в жоден зі списків), його
    треба назвати тут поіменно, а не просто виключити перевірку.
    """
    result = ds_audit.naming_mismatch(ROOT)
    assert result['should_lose_prefix'] == [], (
        'компонентні файли з префіксом page- (ім\'я суперечить суті): '
        + ', '.join(result['should_lose_prefix'])
    )
    assert result['should_gain_prefix'] == [], (
        'посторінкові файли без префікса page- (ім\'я суперечить суті): '
        + ', '.join(result['should_gain_prefix'])
    )


def test_naming_mismatch_catches_component_file_with_page_prefix(tmp_path):
    """Синтетичне доведення: файл із 2+ споживачами (компонентний за межею
    аудиту) і префіксом page- -- це і є розбіжність імені й суті, яку
    naming_mismatch мусить назвати в should_lose_prefix.
    """
    tpl_dir = tmp_path / 'app' / 'templates'
    tpl_dir.mkdir(parents=True)
    for i in (1, 2):
        (tpl_dir / f'consumer{i}.html').write_text(
            '<link rel="stylesheet" href="{{ url_for(\'static\', '
            'filename=\'css/page-shared.css\') }}">\n',
            encoding='utf-8')
    css_dir = tmp_path / 'app' / 'static' / 'css'
    css_dir.mkdir(parents=True)
    (css_dir / 'page-shared.css').write_text('.shared { color: red; }', encoding='utf-8')

    result = ds_audit.naming_mismatch(tmp_path)
    assert result['should_lose_prefix'] == ['page-shared.css'], (
        'page-shared.css -- 2 споживачі, отже компонентний, але з префіксом '
        'page-: має бути названий у should_lose_prefix.'
    )


# Семантика суб'єкта селектора -- пришпилено на літеральних рядках CSS, а
# не на живих файлах проєкту: файли зміняться, а правило "суб'єкт -- це
# останній компаунд, поза дужками псевдокласів" мусить лишатись перевіреним
# незалежно від того, що зараз лежить у app/static/css.

def test_selector_subject_ignores_functional_pseudo_class_argument():
    subjects = ds_audit._selector_subject_classes(
        '.admin-sidebar__link:has(.badge)::after '
    )
    assert subjects == {'admin-sidebar__link'}, (
        ".badge -- аргумент :has(), а не суб'єкт: правило не перестилізовує "
        ".badge, воно лише УМОВНО спрацьовує, коли всередині є .badge."
    )


def test_selector_subject_is_last_compound_of_descendant_selector():
    subjects = ds_audit._selector_subject_classes('.admin-instances-place .badge ')
    assert subjects == {'badge'}, (
        ".admin-instances-place -- предок у descendant-селекторі, не "
        "суб'єкт; .badge -- останній компаунд, саме його стилізує правило."
    )


def test_selector_subject_compound_selector_keeps_every_class_in_it():
    subjects = ds_audit._selector_subject_classes('.card.card--wide ')
    assert subjects == {'card', 'card--wide'}, (
        'card і card--wide стоять в ОДНОМУ компаунді (без комбінатора між '
        'ними) -- обидва суб’єкт цього правила.'
    )


def test_selector_subject_child_combinator_drops_the_parent():
    subjects = ds_audit._selector_subject_classes('.card > .card__title ')
    assert subjects == {'card__title'}, (
        '.card -- предок через дочірній комбінатор >, не суб’єкт.'
    )


def test_selector_subject_comma_list_splits_into_independent_selectors():
    subjects = ds_audit._selector_subject_classes('.foo, .bar ')
    assert subjects == {'foo', 'bar'}


def test_selector_subject_catches_naive_regression():
    """Наївний розбір (усі класи в селекторі, без урахування суб'єкта) дав
    би тут {'foo', 'bar', 'baz', 'qux'}. Цей тест падає, якщо хтось
    поверне такий підрахунок замість суб'єктного.
    """
    subjects = ds_audit._selector_subject_classes(
        '.foo:not(.bar):has(.baz) .qux '
    )
    assert subjects == {'qux'}


# _effective_css -- чиста функція над словниками direct/parents, тож обхід
# графа глибиною 3+ пришпилюється на штучному графі, а не на живих шаблонах
# проєкту (їхня глибина include-ланцюжків може змінитись).

def test_effective_css_walks_three_levels_deep():
    """Історична вада: catalog_gap розгортав extends/include вручну на
    рівно два рівні (ref, потім ref2) і на цьому зупинявся. CSS,
    підключений на третьому рівні вкладеності (партіал у партіалі у
    партіалі), тихо не вважався б підключеним. Сьогодні в проєкті партіали
    третього рівня CSS не лінкують, тож ручне розгортання випадково давало
    правильне число -- цей тест ловить ваду незалежно від того, що зараз
    лежить у app/templates.
    """
    direct = {
        'catalog.html': set(),
        'base.html': set(),
        'partials/header.html': set(),
        'partials/lang_switcher.html': {'lang-switcher.css'},
    }
    parents = {
        'catalog.html': {'base.html'},
        'base.html': {'partials/header.html'},
        'partials/header.html': {'partials/lang_switcher.html'},
        'partials/lang_switcher.html': set(),
    }
    effective = ds_audit._effective_css('catalog.html', direct, parents)
    assert 'lang-switcher.css' in effective, (
        'lang-switcher.css підключений на третьому рівні '
        '(catalog -> base -> header -> lang_switcher). Обхід графа, '
        'обмежений двома рівнями, цей CSS втратить.'
    )


def test_effective_css_stops_on_cycle():
    """extends/include теоретично можуть утворити цикл -- рекурсія без
    захисту від цього піде в нескінченність. `seen` мусить зупиняти обхід
    на повторному вузлі, а не губити CSS, зібраний до цього.
    """
    direct = {'a.html': {'a.css'}, 'b.html': {'b.css'}}
    parents = {'a.html': {'b.html'}, 'b.html': {'a.html'}}
    effective = ds_audit._effective_css('a.html', direct, parents)
    assert effective == {'a.css', 'b.css'}


# --- скоуплений варіант проти справжнього дубліката ----------------------
#
# Різниця вирішальна для концепту, і метрика без неї перебільшувала борг
# утричі (69 замість 18). Клас, оголошений БЕЗ скоупу у двох файлах, --
# справжній дублікат: який вигляд переможе, вирішує порядок підключення.
# Клас, оголошений під предком (`.apple-page .apple-btn`), -- штатний
# варіант компонента для зони сайту: виграє специфічність, детерміновано.
# Храповик на нерозділеному числі спрацьовував би на законному новому
# варіанті, і його вимкнули б першого ж дня.


def _css_tree(tmp_path, files):
    root = tmp_path / 'app' / 'static' / 'css'
    root.mkdir(parents=True)
    for name, body in files.items():
        (root / name).write_text(body, encoding='utf-8')
    return tmp_path


def test_unscoped_declaration_in_two_files_is_a_duplicate(tmp_path):
    root = _css_tree(tmp_path, {
        'a.css': '.widget { color: red; }',
        'b.css': '.widget { color: blue; }',
    })
    assert 'widget' in ds_audit.duplicate_classes(root)
    assert 'widget' not in ds_audit.scoped_variants(root)


def test_scoped_declaration_is_a_variant_not_a_duplicate(tmp_path):
    root = _css_tree(tmp_path, {
        'a.css': '.widget { color: red; }',
        'b.css': '.zone .widget { color: blue; }',
    })
    assert 'widget' not in ds_audit.duplicate_classes(root), (
        '`.zone .widget` -- варіант під предком: він виграє специфічністю '
        'незалежно від порядку підключення, тож це не дублікат.'
    )
    assert 'widget' in ds_audit.scoped_variants(root)


def test_child_and_sibling_combinators_also_count_as_scoped(tmp_path):
    root = _css_tree(tmp_path, {
        'a.css': '.widget { color: red; }',
        'b.css': '.zone > .widget, .other + .widget { color: blue; }',
    })
    assert 'widget' not in ds_audit.duplicate_classes(root)


def test_different_state_is_not_a_duplicate(tmp_path):
    """`.widget` і `.widget:hover` одне одного не перебивають.

    Це різні селектори: базове правило й правило стану. Порядок
    підключення між ними нічого не вирішує, тож дублікатом вони не є.
    """
    root = _css_tree(tmp_path, {
        'a.css': '.widget { color: red; }',
        'b.css': '.widget:hover { color: blue; }',
    })
    assert 'widget' not in ds_audit.duplicate_classes(root)


def test_same_scoped_selector_in_two_files_is_a_duplicate(tmp_path):
    """Скоуп не рятує, якщо селектор ОДНАКОВИЙ у двох файлах.

    `.zone .widget {}` в обох -- однакова вага, ті самі елементи, виграє
    порядок підключення. Правило "скоуплений = не борг" це ховало: саме
    так у проєкті лишились непоміченими шість класів `.apple-page
    .iprm-program*`, оголошених однаково в apple-pages.css і
    course-landing.css.
    """
    root = _css_tree(tmp_path, {
        'a.css': '.zone .widget { max-width: 980px; }',
        'b.css': '.zone .widget { max-width: 1200px; }',
    })
    assert 'widget' in ds_audit.duplicate_classes(root)


def test_compound_qualified_state_classes_do_not_collide(tmp_path):
    """`.toast.is-visible` і `.dialog.is-visible` -- різні селектори.

    Обидва правила добирають різні елементи, тож спільний клас стану
    зіткненням не є. Метрика, яка рахувала компаунд голим оголошенням,
    хибно показувала `.is-visible` дублікатом у чотирьох файлах.
    """
    root = _css_tree(tmp_path, {
        'a.css': '.toast.is-visible { opacity: 1; }',
        'b.css': '.dialog.is-visible { opacity: 1; }',
    })
    assert 'is-visible' not in ds_audit.duplicate_classes(root)
