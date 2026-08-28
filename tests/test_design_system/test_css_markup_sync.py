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


def _read(dirpath, pattern):
    return '\n'.join(p.read_text(encoding='utf-8') for p in dirpath.rglob(pattern))


def _css_text():
    return '\n'.join(p.read_text(encoding='utf-8') for p in CSS_DIR.glob('*.css'))


def _template_text():
    """Лише шаблони адмінки.

    Сертифікати, листи й частина публічних сторінок несуть власні <style>
    просто в шаблоні (PDF і пошта інакше не вміють), і їхні класи в наших
    css-файлах не мають бути за визначенням.
    """
    return _read(TPL_DIR / 'admin', '*.html')


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
    """Мертве правило заманює наступного зробити другу копію компонента."""
    tpl = _template_text()
    js = _js_text()
    py = _read(ROOT / 'app', '*.py')
    haystack = tpl + js + py
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
            if re.search(re.escape(stem) + r'(--|__)[\w-]*\s*\{\{', haystack):
                continue
            dead.append(f'{path.name}: .{cls}')
    assert not dead, (
        'правила без жодного користувача:\n  ' + '\n  '.join(dead)
        + '\nПрибрати -- або, якщо компонент потрібен, показати його '
          'на /design-system і вживати.'
    )
