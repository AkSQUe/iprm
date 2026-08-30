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

ДУБЛІКАТ -- це ОДНАКОВИЙ СЕЛЕКТОР у двох файлах, а не однаковий клас.
Два правила перебивають одне одного порядком підключення лише тоді, коли
селектор той самий: у них однакова вага й вони добирають ті самі елементи.
Усе інше вирішується специфічністю, детерміновано:

  .alert {}            в admin.css і common.css   -> ДУБЛІКАТ
  .apple-page .iprm-program {} у двох файлах      -> ДУБЛІКАТ (скоуп не рятує)
  .alert {} проти .zone .alert {}                 -> варіант, не борг
  .toast.is-visible проти .dialog.is-visible      -> різні елементи, не борг
  .widget {} проти .widget:hover {}               -> різні стани, не борг

Метрику довелось уточнювати тричі, і кожне уточнення міняло число:
69 (будь-який спільний клас) -> 18 (клас без скоупу) -> 20 (спільний
селектор). Останнє число більше за попереднє не тому, що борг виріс, а
тому, що правило "скоуплений = не борг" ховало шість класів
`.apple-page .iprm-program*`, оголошених ОДНАКОВО у двох файлах.

Клас усередині селектора рахується лише в СУБ'ЄКТІ правила -- останній
компаунд, поза аргументами :not()/:has()/:is()/:where(): згадка класу як
предка нічого не перестилізовує.

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


def _selector_owners(root):
    """{нормалізований селектор: {файли, де він оголошений}}.

    Ключ -- САМ СЕЛЕКТОР, а не клас. Два правила перебивають одне одного
    порядком підключення лише тоді, коли селектор той самий: тоді в них
    однакова вага й вони добирають ті самі елементи. Різні скоупи
    (`.alert` проти `.zone .alert`) вирішуються специфічністю,
    детерміновано, і дублікатом не є.
    """
    owners = {}
    for path in sorted((root / 'app' / 'static' / 'css').rglob('*.css')):
        css = _COMMENT.sub(' ', path.read_text(encoding='utf-8'))
        for head in re.findall(r'([^{}]+)\{', css):
            if head.lstrip().startswith('@'):
                continue
            for selector in head.split(','):
                norm = re.sub(r'\s+', ' ', selector.strip())
                if not norm or '.' not in norm:
                    continue
                owners.setdefault(norm, set()).add(path.name)
    return owners


def duplicate_selectors(root=ROOT):
    """Селектори, оголошені ОДНАКОВО у 2+ файлах."""
    return {s: sorted(f) for s, f in sorted(_selector_owners(root).items())
            if len(f) > 1}


def duplicate_classes(root=ROOT):
    """СПРАВЖНІ дублікати: клас, якого торкається селектор, оголошений
    однаково у 2+ файлах.

    Саме тут порушується критерій концепту -- який вигляд переможе,
    вирішує порядок підключення, тож правка компонента до частини сторінок
    не доходить. Класи, оголошені в різних файлах під РІЗНИМИ скоупами, --
    не сюди: див. `scoped_variants`.
    """
    classes = {}
    for selector, files in duplicate_selectors(root).items():
        for cls in _selector_subject_classes(selector):
            classes.setdefault(cls, set()).update(files)
    return {c: sorted(f) for c, f in sorted(classes.items())}


def scoped_variants(root=ROOT):
    """Клас оголошений у 2+ файлах, але жодного СПІЛЬНОГО селектора.

    Тобто різні скоупи: `.alert` в одному файлі, `.zone .alert` в іншому.
    Виграє специфічність, детерміновано й незалежно від порядку -- це
    штатний варіант компонента для зони сайту, а не борг.
    """
    everywhere = {}
    for path in sorted((root / 'app' / 'static' / 'css').rglob('*.css')):
        for cls in _declared_classes(path):
            everywhere.setdefault(cls, set()).add(path.name)
    true = duplicate_classes(root)
    return {c: sorted(f) for c, f in sorted(everywhere.items())
            if len(f) > 1 and c not in true}


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


def _unconditional_css_links(text):
    """CSS-файли, підключені БЕЗУМОВНО -- поза `{% if %}`.

    Для підрахунку споживачів умовний `<link>` рахувати можна: сторінка
    його ІНОДІ отримує. Для каталогу -- ні: він мусить показувати компонент
    ЗАВЖДИ. `upcoming-events.css` і `certdata-reminder.css` підключені в
    base.html під прапорцями, які фабрика обнуляє для блупринта admin, тож
    на сторінці каталогу вони не вантажаться ніколи -- а сторож вважав їх
    показаними й мовчав.
    """
    stripped = re.sub(r'{%-?\s*if\b.*?{%-?\s*endif\s*-?%}', ' ', text, flags=re.S)
    return _css_links(stripped)


def catalog_gap(root=ROOT):
    """Компонентні файли, яких каталог не підключає БЕЗУМОВНО."""
    texts = _templates(root)
    direct, parents = _link_graph(texts)
    direct = {name: _unconditional_css_links(text) for name, text in texts.items()}
    linked = set()
    for name in _catalog_names(root):
        linked |= _effective_css(name, direct, parents)
    return sorted(set(classify_css(root)['component']) - linked)


def page_overrides(root=ROOT):
    """{файл: {клас: [шаблони]}} -- спільні компоненти, які перестилізовує
    ПОСТОРІНКОВИЙ файл.

    Четверте число концепту, яке досі рахувалось вручну й неправильно.
    Рахувати «декоративні оголошення в page-*» безглуздо: декор, унікальний
    для однієї сторінки, за суттю посторінковий і має там жити. Порушення --
    це коли `page-*.css` перестилізовує клас, який вживають ІНШІ сторінки:
    тоді правка компонента до цієї сторінки не доходить повністю.

    Різниця в масштабі помітна: декоративних оголошень у page-* сімсот із
    гаком, а спільних компонентів, які там перестилізовують, -- два десятки.
    Перше число лякає й нічого не каже, друге -- робочий список.

    Каталог із підрахунку споживачів виключений: він показує компоненти.
    """
    tpl = root / 'app' / 'templates'
    texts = {p.relative_to(tpl).as_posix(): p.read_text(encoding='utf-8', errors='ignore')
             for p in tpl.rglob('*.html')}
    out = {}
    for path in sorted((root / 'app' / 'static' / 'css').rglob('page-*.css')):
        for cls in sorted(_declared_classes(path)):
            pattern = re.compile(r'class="[^"]*\b' + re.escape(cls) + r'\b')
            users = [n for n, text in texts.items()
                     if pattern.search(text) and not n.startswith('design_system/')]
            if len(users) > 1:
                out.setdefault(path.name, {})[cls] = users
    return out


def cross_domain_components(root=ROOT):
    """{клас: [домени]} -- класи-блоки, ужиті БІЛЬШ НІЖ одним доменом.

    Домен -- тека верхнього рівня в `app/templates` (`auth`, `admin`,
    `courses`, `partials`...). Клас, який вживають два різні домени, --
    справжній спільний компонент: його неминуче шукатиме наступний, і якщо
    в каталозі його не видно, він напише свій.

    Чому не всі класи компонентних файлів. Їх 421, і 271 у каталозі немає.
    Але "компонентний файл" не дорівнює "перевикористовуваний компонент":
    `blog-card` живе у двох блогових шаблонах і жодній іншій сторінці не
    потрібен. Тест на всі 421 упав би першого ж дня з 271 порушенням, і
    його вимкнули б -- рівно те, проти чого цей проєкт і працює.

    Крос-доменних -- 90, і це вже робочий список.
    """
    tpl = root / 'app' / 'templates'
    texts = {p.relative_to(tpl).as_posix(): p.read_text(encoding='utf-8', errors='ignore')
             for p in tpl.rglob('*.html')}
    component = classify_css(root)['component']
    out = {}
    for name in sorted(component):
        for cls in sorted(_declared_classes(root / 'app' / 'static' / 'css' / name)):
            if '__' in cls or '--' in cls or cls.startswith('is-'):
                continue
            pattern = re.compile(r'class="[^"]*\b' + re.escape(cls) + r'\b')
            domains = {n.split('/')[0] if '/' in n else 'root'
                       for n, text in texts.items()
                       if pattern.search(text) and not n.startswith('design_system/')}
            if len(domains) > 1:
                out[cls] = sorted(domains)
    return out


def _rule_bodies(path, split_selectors=True):
    """[(медіа, селектор, {властивість: значення})] -- правила одного файлу.

    `split_selectors=False` віддає БЛОК цілим: селектори через кому
    лишаються одним записом. Це потрібно пошукові копій -- одне
    правило з чотирма селекторами не є чотирма копіями, воно вже
    зведене.
    """
    text = re.sub(r'/\*.*?\*/', '', path.read_text(encoding='utf-8'), flags=re.S)
    out, media, buf, i = [], '', [], 0
    while i < len(text):
        ch = text[i]
        if ch == '{':
            head = ''.join(buf).strip()
            buf = []
            if head.startswith('@'):
                media = head
                i += 1
                continue
            body, j, depth = '', i + 1, 1
            while j < len(text) and depth:
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if not depth:
                        break
                body += text[j]
                j += 1
            props = {k: ' '.join(v.split())
                     for k, v in re.findall(r'([-a-z]+)\s*:\s*([^;]+)', body)}
            if split_selectors:
                for sel in head.split(','):
                    out.append((media, ' '.join(sel.split()), props))
            else:
                out.append((media, ' '.join(head.split()), props))
            i = j + 1
            continue
        if ch == '}':
            media, buf = '', []
            i += 1
            continue
        buf.append(ch)
        i += 1
    return out


_VENDOR_PSEUDO = re.compile(r'::-(?:webkit|moz|ms)-')


def rule_clones(root=ROOT, min_props=3):
    """{(медіа, набір): [(файл, селектор)]} -- ОДНАКОВИЙ набір під різними
    селекторами.

    Це не дублікат у сенсі `duplicate_selectors`: селектори різні, вони не
    конфліктують, і порядок підключення ні на що не впливає. Саме тому
    жодна інша міра цього не бачить, а `scoped_variants` навіть зараховує
    такі правила в «не борг».

    Але однаковий НАБІР означає, що правило описує один компонент,
    скопійований під кілька скоупів. `.blog-comment-form .form-input` у
    `blog.css` і `.form-section .form-input` у `common.css` побайтово
    однакові -- це компактне поле вводу, про яке кожна форма домовилась
    окремо. Правка одного до решти не доходить, і саме це порушує керівний
    принцип, хоч дублікатів у проєкті нуль.

    Правила менш ніж із `min_props` властивостями не рахуються: два
    оголошення з одного `display: flex` збігаються випадково.

    **Число цієї міри -- привід подумати, а не вирок.** Поділ на «варті
    уваги» (5+ властивостей АБО 4+ копій) відсіює дрібне, але не відрізняє
    ІДІОМУ від компонента, і на двох групах він помиляється:

    * `list-style: none; margin: 0; padding: 0` у шести місцях;
    * `display: flex; align-items: center; gap: 8px` у шести.

    Обидві пройшли фільтр за кількістю копій. Але ніхто не змінює
    `list-style: none` централізовано й не чекає, що правка дійде всюди --
    це спосіб написати «список без маркерів», а не компонент. Для
    порівняння, `.iprm-img-cover` звести було правильно: там і чотирнадцять
    копій, і рішення ВИГЛЯДУ, яке дизайнер справді може змінити (cover
    проти contain).

    Практична ознака, якою це перевіряється: чи мають задіяні класи ІНШІ
    правила. У п'яти з дванадцяти єдиним правилом було саме те, що
    прибиралося б -- після зведення клас лишився б у розмітці без жодного
    правила, і сторож «клас без правила» впав би справедливо.

    Блок береться ЦІЛИМ. Перша версія цієї міри ділила список селекторів
    через кому й рахувала кожен окремою копією -- через це вже зведене
    правило `.field-invalid, input.field-invalid, select.field-invalid,
    textarea.field-invalid` виглядало як чотири копії, хоча воно і є
    прикладом того, до чого міра закликає. Число через це було завищене.
    """
    groups = {}
    for path in sorted((root / 'app' / 'static' / 'css').rglob('*.css')):
        for media, sel, props in _rule_bodies(path, split_selectors=False):
            if len(props) < min_props:
                continue
            groups.setdefault((media, tuple(sorted(props.items()))),
                              []).append((path.name, sel))
    out = {}
    for key, where in groups.items():
        if len(where) < 2:
            continue
        # Префіксні псевдоелементи ОБОВ'ЯЗКОВО пишуться окремими правилами:
        # браузер, який не знає селектора, викидає ціле правило, тож
        # `::file-selector-button` і `::-webkit-file-upload-button` не можна
        # об'єднати комою. Це вимушене дублювання, а не борг.
        if any(_VENDOR_PSEUDO.search(sel) for _, sel in where):
            continue
        out[key] = where
    return out


def catalog_only_components(root=ROOT):
    """{клас: файл} -- компоненти, яких не вживає НІХТО, крім каталогу.

    Каталог існує, щоб побачити наявний компонент було легше, ніж написати
    свій. Але в нього є зворотний бік, на який легко натрапити, роблячи
    вітрину чеснішою: якщо мертвий компонент показати живими класами, у
    нього з'являється споживач -- сама вітрина. Після цього сторож "правило
    без розмітки" мовчить назавжди, бо розмітка є, і мертвий CSS дістає
    алібі.

    Так уже сталося з `.iprm-target-grid`/`.iprm-target-card`: вони повністю
    оформлені в глобальному `apple-pages.css`, справжня секція аудиторії
    вживає інакше названий `.iprm-audience-card`, і єдиним їхнім споживачем
    став таб молекул.

    **Межа, якої ця міра не перетне.** Ім'я класу, ЗІБРАНЕ в рантаймі,
    невидиме для будь-якого статичного скану: `admin-status-select.js`
    робить `'admin-toast--' + variant`, тож літерального
    `admin-toast--success` немає ніде -- ні в шаблонах, ні в скриптах.
    Такий клас виглядатиме мертвим, хоч він живий.

    Перш ніж видаляти щось за підказкою цієї міри, грепни КОРІНЬ імені
    (`admin-toast--`), а не повне ім'я.

    Це не наказ видаляти. Клас звідси -- або мертвий CSS, або компонент,
    який комусь варто нарешті вжити; вибір залежить від того, чи він
    потрібен. Але лишати його непоміченим не можна саме тому, що вітрина
    робить його схожим на живий.
    """
    tpl = root / 'app' / 'templates'
    texts = {p.relative_to(tpl).as_posix(): p.read_text(encoding='utf-8', errors='ignore')
             for p in tpl.rglob('*.html')}
    # Класи ставить не лише шаблон. `page-courses-schedule.js` і
    # `blog-editor.js` будують розмітку рядками, і клас, який живе ТІЛЬКИ
    # там, без цього сканування виглядав би мертвим -- а міра радила б його
    # видалити. Саме так `.iprm-focus-ring` потрапив у список одразу після
    # того, як його завели.
    js_dir = root / 'app' / 'static' / 'js'
    js_texts = {'js/' + p.name: p.read_text(encoding='utf-8', errors='ignore')
                for p in js_dir.glob('*.js')} if js_dir.exists() else {}

    component = classify_css(root)['component']
    out = {}
    for name in sorted(component):
        for cls in sorted(_declared_classes(root / 'app' / 'static' / 'css' / name)):
            if '__' in cls or '--' in cls or cls.startswith('is-'):
                continue
            pattern = re.compile(r'class="[^"]*\b' + re.escape(cls) + r'\b')
            users = [n for n, text in texts.items() if pattern.search(text)]
            # У JS клас трапляється і в `class="..."`, і в об'єкті атрибутів
            # (`{'class': 'a b'}`), тож шукаємо саме ім'я в межах слова.
            js_pattern = re.compile(r'\b' + re.escape(cls) + r'\b')
            users += [n for n, text in js_texts.items() if js_pattern.search(text)]
            if not users:
                continue
            if all(n.startswith('design_system/') or n.startswith('admin/design_system')
                   for n in users):
                out[cls] = name
    return out


# Властивості, які ЗАДАЮТЬ ВИГЛЯД. Inline-стиль із такою властивістю в
# каталозі -- підробка компонента: вітрина малює його значеннями, СКОПІЙОВАНИМИ
# з CSS, а не самим компонентом. Копія розходиться, і каталог починає брехати
# саме там, куди дивляться, щоб не писати копію.
_LOOK = re.compile(r'\b(font-size|font-weight|font-family|background|border'
                   r'|border-radius|box-shadow|color|letter-spacing)\s*:')


def catalog_mockups(root=ROOT):
    """{файл: кількість} -- inline-стилі каталогу, що ПІДРОБЛЯЮТЬ вигляд.

    Риштування розкладки (`display`, `flex`, `margin`, `width`) сюди не
    входить: воно лише розставляє демо на сторінці й нічого про компонент
    не стверджує.

    Приклад із життя: секція hero показувала заголовок як
    `font-size: clamp(2rem, 5vw, 3rem); font-weight: 800`, тоді як
    `.iprm-hero__title` має `24px` і `700`. Вітрина показувала компонент
    удвічі більшим за нього самого.
    """
    out = {}
    for path in sorted((root / 'app' / 'templates' / 'design_system').glob('_tab_*.html')):
        n = sum(1 for style in re.findall(r'style="([^"]*)"',
                                          path.read_text(encoding='utf-8'))
                if _LOOK.search(style))
        if n:
            out[path.name] = n
    return out


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
    ap.add_argument('--rebaseline', action='store_true',
                    help='перезаписати baseline, навіть якщо число зросло -- '
                         'ЛИШЕ коли змінилась сама метрика, не код')
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
    print('\nДУБЛІКАТИ (ОДНАКОВИЙ селектор у 2+ файлах): %d класів, %d селекторів'
          % (len(dupes), len(duplicate_selectors())))
    for cls, files in list(dupes.items())[:10]:
        print('   .%-28s %s' % (cls, ', '.join(files)))
    if len(dupes) > 10:
        print('   ... ще %d' % (len(dupes) - 10))

    variants = scoped_variants()
    print('\nРІЗНІ СКОУПИ (не борг -- виграє специфічність, '
          'а не порядок): %d' % len(variants))
    print('\nКОМПОНЕНТНІ ФАЙЛИ ПОЗА КАТАЛОГОМ: %d' % len(gap))
    for name in gap:
        print('   ' + name)
    clones = rule_clones()
    # Не кожен близнюк -- борг. `display: flex; gap: 8px; align-items: center`
    # у шести місцях -- це ідіома верстки, а не компонент, чию правку хтось
    # чекає побачити всюди. Ознака СПРАВЖНЬОГО компонента -- або обсяг
    # (5+ властивостей), або поширеність (4+ копій): обкладинку зображення
    # варто було звести саме тому, що трьох властивостей було чотирнадцять.
    big = {k: v for k, v in clones.items() if len(k[1]) >= 5 or len(v) >= 4}
    small = {k: v for k, v in clones.items() if k not in big}
    print('\nПРАВИЛА-БЛИЗНЮКИ (однаковий набір під різними селекторами)')
    print('   варті уваги (5+ властивостей АБО 4+ копій): %d груп, %d копій'
          % (len(big), sum(len(v) - 1 for v in big.values())))
    print('   ідіома верстки (мале правило у 2-3 місцях): %d груп, %d копій'
          % (len(small), sum(len(v) - 1 for v in small.values())))
    for (media, props), where in sorted(big.items(), key=lambda x: -len(x[1]))[:5]:
        print('   %d копій у %d файлах, %d власт. -- %s'
              % (len(where), len({f for f, _ in where}), len(props),
                 ', '.join(p for p, _ in props[:4])))

    only = catalog_only_components()
    print('\nЖИВУТЬ ЛИШЕ У ВІТРИНІ (єдиний споживач -- каталог): %d' % len(only))
    for cls, name in sorted(only.items()):
        print('   .%-28s %s' % (cls, name))

    mockups = catalog_mockups()
    print('\nПІДРОБЛЕНІ ДЕМО В КАТАЛОЗІ (inline-стиль задає вигляд): %d'
          % sum(mockups.values()))
    for name, n in sorted(mockups.items(), key=lambda x: -x[1]):
        print('   %-34s %d' % (name, n))

    overrides = page_overrides()
    n_over = sum(len(v) for v in overrides.values())
    print('\nСПІЛЬНІ КОМПОНЕНТИ, ПЕРЕСТИЛІЗОВАНІ В page-*: %d класів у %d файлах'
          % (n_over, len(overrides)))
    for name, classes in sorted(overrides.items()):
        print('   %-38s %s' % (name, ', '.join('.' + c for c in sorted(classes))))

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
        if BASELINE.exists() and not args.rebaseline:
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
