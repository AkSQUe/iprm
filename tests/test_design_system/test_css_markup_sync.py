"""CSS і розмітка адмінки мусять збігатись в обидва боки.

Два зустрічні скани. Кожен уже знаходив справжні вади, яких не видно ні
оком, ні рештою тестів:

* клас у розмітці без правила -- `.admin-badge` стояв на шести плашках, а
  правила для нього не було в жодному файлі: колонка «Статус» друкувалась
  голим словом. Так само `.btn-admin--ghost` малював дві кнопки текстом, а
  `.form-readonly` -- п'ять значень у картці запиту;
* правило без розмітки -- мертвий `.admin-filter-chips` (копія стрічки
  зрізів) і `.participant-hint` (копія `.form-hint`). Небезпечні вони тим,
  що наступний, хто шукатиме готовий компонент, знайде саме їх, і в системі
  знову з'явиться другий спосіб зробити те саме.

Обидва скани мусять уміти в жинжу: `admin-stat-card--{{ mod }}` дає в
тексті шаблону обрізок `admin-stat-card--`, а правило `.admin-stat-card--danger`
у CSS при цьому живе й діє.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS_DIR = ROOT / 'app' / 'static' / 'css'
TPL_DIR = ROOT / 'app' / 'templates'
JS_DIR = ROOT / 'app' / 'static' / 'js'

# Класи, які приходять не з наших файлів або тримаються скриптами.
EXTERNAL = {
    'material-symbols-rounded',   # клас іконкового шрифту
}

# Теги (`<...>`) і жинжа-блоки (`{{ ... }}`, `{% ... %}`) -- саме там живуть
# СПРАВЖНІ вживання класу: у class=, у kwarg cls= макроса icon(), у
# {% set %}-словнику, звідки клас підставляється рядком. Текст МІЖ тегами
# (проза підказок на кшталт `<p class="ds-hint">...</p>`) навмисно НЕ
# островом: інакше слово-згадка класу в описі рахується користувачем,
# хоча в class= клас ніде не стоїть -- саме так мертвий клас зеленів від
# одного слова в каталозі (I6).
_CODE_ISLAND = re.compile(r'<[^>]*>|\{[{%].*?[%}]\}', re.S)


def _code_text(text):
    """`text` без прози -- лише вміст тегів і жинжа-виразів/стейтментів."""
    return ' '.join(_CODE_ISLAND.findall(text))


def _read(dirpath, pattern):
    return '\n'.join(p.read_text(encoding='utf-8') for p in dirpath.rglob(pattern))


def _css_text():
    return '\n'.join(p.read_text(encoding='utf-8') for p in CSS_DIR.glob('*.css'))


def _template_text():
    """Шаблони адмінки й партіали каталогу дизайн-системи.

    Сертифікати, листи й частина публічних сторінок несуть власні <style>
    просто в шаблоні (PDF і пошта інакше не вміють), і їхні класи в наших
    css-файлах не мають бути за визначенням.

    `design_system/_tab_*.html` -- окремий верхньорівневий каталог (не під
    `admin/`), хоча інклюдиться лише з `admin/design_system.html` і показує
    розмітку `page-admin-design-system.css`. Без нього клас, ужитий тільки
    на вітрині каталогу, сканер мертвих правил бачить як осиротілий.
    """
    return _read(TPL_DIR / 'admin', '*.html') + _read(TPL_DIR / 'design_system', '*.html')


def _js_text():
    return _read(JS_DIR, '*.js') if JS_DIR.exists() else ''


def _classes_in_markup():
    """Класи з `class="..."`, крім обрізків, що лишає жинжа-вираз."""
    text = _template_text()
    out = set()
    for attr in re.findall(r'class="([^"]*)"', text):
        # прибираємо вирази цілком: те, що вони підставлять, перевірити тут
        # неможливо, а їхні уламки дали б хибні спрацювання
        cleaned = re.sub(r'\{[{%].*?[%}]\}', ' ', attr, flags=re.S)
        for token in cleaned.split():
            if re.fullmatch(r'[a-z][\w-]*', token):
                out.add(token)
    return out


def _classes_in_css():
    css = re.sub(r'/\*.*?\*/', ' ', _css_text(), flags=re.S)
    out = set()
    for head in re.findall(r'([^{}]+)\{', css):
        if head.lstrip().startswith('@'):
            continue
        out |= set(re.findall(r'\.([a-zA-Z][\w-]*)', head))
    return out


def test_every_class_in_markup_has_a_rule():
    """Клас у розмітці, для якого немає жодного правила, малюється дефолтом."""
    css = _classes_in_css()
    js = _js_text()
    tpl = _template_text()
    missing = []
    for cls in sorted(_classes_in_markup()):
        if cls in css or cls in EXTERNAL:
            continue
        # гачок для скрипта -- не для стилю
        if re.search(r'[\'"`.#]%s\b' % re.escape(cls), js):
            continue
        # блок BEM без власного правила -- нормально, поки є його елементи
        if any(c.startswith(cls + '__') or c.startswith(cls + '--') for c in css):
            continue
        # клас, який десь будується з жинжа-виразу (admin-stat-card--{{ mod }})
        if re.search(re.escape(cls) + r'-*\s*\{\{', tpl):
            continue
        missing.append(cls)
    assert not missing, (
        'класи є в розмітці, але правил для них немає ніде: '
        + ', '.join(missing)
        + '.\nДодайте правило в дизайн-систему або візьміть наявний компонент '
          '(перелік -- на /design-system).'
    )


def test_admin_css_has_no_unused_rules():
    """Мертве правило заманює наступного зробити другу копію компонента.

    "Використаний" рахується лише вживання в коді -- тегах (`class=`,
    kwarg `cls=` макроса `icon()`) і жинжа-виразах/стейтментах (`{{ }}`,
    `{% set %}`), а не будь-яке входження слова в прозовий текст партіала.
    Раніше сканер шукав клас підрядком по ВСЬОМУ тексту шаблонів -- і
    будь-яка згадка класу словом ("admin-zzztest" у підказці на вітрині)
    рахувалась як користувач, хоч насправді клас ніде не СТОЯВ у class=.
    Мертвий клас зеленів від одного слова в каталозі (I6). `_code_text`
    звужує пошук до тегів і жинжа-блоків -- туди, де класи РЕАЛЬНО
    потрапляють у розмітку, і викидає прозу підказок.
    """
    tpl_code = _code_text(_template_text())
    js = _js_text()
    py = _read(ROOT / 'app', '*.py')
    haystack = tpl_code + js + py
    dead = []
    for path in sorted(CSS_DIR.glob('*.css')):
        if not path.name.startswith(('admin', 'page-admin')):
            continue
        css = re.sub(r'/\*.*?\*/', ' ', path.read_text(encoding='utf-8'), flags=re.S)
        names = set()
        for head in re.findall(r'([^{}]+)\{', css):
            if head.lstrip().startswith('@'):
                continue
            names |= set(re.findall(r'\.([a-z][\w-]{3,})', head))
        for cls in sorted(names):
            if re.search(r'(?<![\w-])%s(?![\w-])' % re.escape(cls), haystack):
                continue
            # модифікатор, який збирає жинжа: `.wh-action--created` у CSS,
            # `wh-action--{{ x }}` у шаблоні
            stem = re.split(r'--|__', cls)[0]
            if re.search(re.escape(stem) + r'(--|__)[\w-]*\s*\{\{', tpl_code):
                continue
            dead.append(f'{path.name}: .{cls}')
    assert not dead, (
        'правила без жодного користувача:\n  ' + '\n  '.join(dead)
        + '\nПрибрати -- або, якщо компонент потрібен, показати його '
          'на /design-system і вживати.'
    )

# Токени, яких у CSS немає НАВМИСНО: їх ставить скрипт у рантаймі через
# style.setProperty, а CSS лише читає.
RUNTIME_TOKENS = {
    '--iprm-progress',   # progress-fill.js малює смугу заповнення
}

_TOKEN_NAME = re.compile(r'--(?:iprm|apple)-[\w-]*')


def _declared_tokens():
    out = set()
    for path in CSS_DIR.rglob('*.css'):
        out |= set(re.findall(r'(--[a-z][\w-]*)\s*:', path.read_text(encoding='utf-8')))
    return out


def test_every_token_named_outside_css_exists():
    """Ім'я токена, вимовлене в каталозі чи в JS, мусить існувати.

    Дві різні вади, обидві тихі, обидві вже траплялись за один прохід.

    `molecular-background.js` читав `--apple-accent-rgb` і
    `--apple-orange-rgb` через getComputedStyle. Після перейменування
    токенів обидва повертали порожньо, і код падав на зашиті запасні
    значення -- а вони НЕ дорівнювали справжнім. Тло змінило колір без
    помилки в консолі й без сліду в знімку обчислених стилів: полотно малює
    скрипт, а знімок дивиться на CSS.

    Проза каталогу називала 26 старих імен по всіх табах. Сторож підробок
    цього не бачить -- він перевіряє inline-стилі, а не слова. Вітрина
    брехала знову, тільки підписами.

    Обрізки жинжі (`--iprm-badge-{{ status }}` дає в тексті
    `--iprm-badge-`) відкидаються за хвостовим дефісом. BEM-модифікатори
    (`--sm`, `--draft`) під патерн не підпадають узагалі: він вимагає
    префікса проєкту.
    """
    declared = _declared_tokens() | RUNTIME_TOKENS
    sources = sorted((TPL_DIR / 'design_system').glob('_tab_*.html'))
    sources += sorted((TPL_DIR / 'admin').glob('design_system*.html'))
    sources += sorted(JS_DIR.glob('*.js'))

    missing = {}
    for path in sources:
        for name in sorted(set(_TOKEN_NAME.findall(path.read_text(encoding='utf-8')))):
            if name.endswith('-') or name in declared:
                continue
            missing.setdefault(name, []).append(path.name)

    assert not missing, (
        'згадані імена токенів, яких немає в жодному CSS-файлі: '
        + '; '.join('%s (%s)' % (n, ', '.join(f)) for n, f in sorted(missing.items()))
        + '\nЯкщо токен перейменували -- оновіть і тих, хто його НАЗИВАЄ: '
          'JS читає токени через getComputedStyle і мовчки падає на запасне '
          'значення, а каталог починає документувати неіснуючу палітру.'
    )

# Стани і псевдоелементи. Правило, чий список селекторів містить і те, і
# те, майже завжди -- наслідок склеювання двох правил, а не задум.
_STATE = re.compile(r':(?:focus|hover|active|checked|disabled'
                    r'|focus-visible|focus-within)\b')
_PSEUDO_EL = re.compile(r'::(?:placeholder|before|after|marker|selection'
                        r'|file-selector-button|-webkit-[\w-]+|-moz-[\w-]+)')


def test_no_rule_mixes_state_with_pseudo_element():
    """Список селекторів не має змішувати стан із псевдоелементом.

    Це сторож проти конкретної аварії, яка вже сталася. Видаляючи правило
    кільця фокуса з `admin.css`, я збігся регексом із ДРУГОГО з п'яти
    селекторів. Чотири зникли разом із тілом, перший лишився висіти:

        .admin-with-sidebar .form-section .form-input:focus,
        /* коментар про видалене правило */
        .admin-with-sidebar .form-section .form-input::placeholder,
        ... { color: var(--apple-gray); }

    Кома коментарем не закривається, тож парсер приклеїв висячий селектор
    до правила плейсхолдера, і текст поля в адмінській формі ставав сірим
    ПІД ЧАС НАБОРУ.

    Чому це не спіймав знімок обчислених стилів: він не знімає станів.
    Нічого не сфокусоване, нічого не під курсором, тож `:focus` і `:hover`
    для нього не існують -- а саме там живуть найтихіші регресії.

    Легітимних змішувань у проєкті нуль, тож сторож не має винятків. Якщо
    колись знадобиться справді змішати -- розділіть на два правила: читач
    усе одно не здогадається, що ви мали на увазі.
    """
    import sys
    sys.path.insert(0, str(ROOT / 'tools' / 'ds'))
    import ds_audit

    mixed = []
    for path in sorted(CSS_DIR.rglob('*.css')):
        for _media, sel, _props in ds_audit._rule_bodies(path, split_selectors=False):
            parts = [s.strip() for s in sel.split(',') if s.strip()]
            if len(parts) < 2:
                continue
            states = [s for s in parts if _STATE.search(s) and not _PSEUDO_EL.search(s)]
            pseudos = [s for s in parts if _PSEUDO_EL.search(s)]
            if states and pseudos:
                mixed.append('%s: %s + %s' % (path.name, states[0], pseudos[0]))

    assert not mixed, (
        'правила, де стан змішано з псевдоелементом (майже завжди -- склеєні '
        'два правила): ' + '; '.join(mixed)
        + '\nПеревірте, чи не лишився висячий селектор від видаленого правила: '
          'кома НЕ закривається коментарем, і список тягнеться далі.'
    )
