"""Список виключень молекулярного фону не має містити мертвих імен.

`molecular-background.css` піднімає всіх прямих дітей `<body>` над фоном
правилом `position: relative; z-index: 1`, а body-level fixed-оверлеї
виключає з нього ланцюжком `:not(.клас)`. Специфічність цього правила
величезна (десяток `:not()` плюс `#id`), тож будь-який оверлей, якого в
списку немає, мовчки втрачає `position: fixed` і високий `z-index`.

Мовчки -- ключове слово. Помилки в консолі немає, JS відпрацьовує до
кінця, клас `--open` додається; просто оверлей лягає в потік документа з
нульовою висотою десь під кінець сторінки, і користувач бачить, що
"модалка не відкривається".

Саме це сталося з лайтбоксом: його винесли з `blog.css` в окремий
`lightbox.css` і перейменували `.blog-lightbox` -> `.iprm-lightbox`, а
виключення лишилось зі старим іменем. Зламались одразу всі три місця, де
компонент живе -- галереї блогу, галерея курсу, регалії тренера.

Сторож перевіряє те, що видно статично: чи кожне ім'я зі списку ще
існує в коді. Мертве ім'я означає, що перейменування пройшло повз список,
і якийсь оверлей зараз перебитий.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS_FILE = ROOT / 'app' / 'static' / 'css' / 'molecular-background.css'
TPL_DIR = ROOT / 'app' / 'templates'
JS_DIR = ROOT / 'app' / 'static' / 'js'
CSS_DIR = ROOT / 'app' / 'static' / 'css'

_RULE = re.compile(r'body\s*>\s*\*?(:not\([^{]*?\))\s*\{', re.S)
_NOT_CLASS = re.compile(r':not\(\.([A-Za-z0-9_-]+)\)')


def _excluded_classes():
    text = CSS_FILE.read_text(encoding='utf-8')
    match = _RULE.search(text)
    assert match, (
        'у molecular-background.css не знайдено правила `body > *:not(...)`. '
        'Якщо його свідомо прибрали -- прибирайте і цей сторож; якщо '
        'переписали -- полагодьте розбір, інакше він мовчки нічого не перевіряє.'
    )
    return _NOT_CLASS.findall(match.group(1))


def _sources():
    parts = []
    for directory, pattern in ((TPL_DIR, '*.html'), (JS_DIR, '*.js')):
        for path in directory.rglob(pattern):
            parts.append(path.read_text(encoding='utf-8'))
    # CSS теж: оверлей може будуватись у шаблоні, а клас мати правила лише тут.
    for path in CSS_DIR.glob('*.css'):
        if path != CSS_FILE:
            parts.append(path.read_text(encoding='utf-8'))
    return '\n'.join(parts)


def test_exclusions_reference_live_classes():
    """Кожен виключений клас мусить існувати поза самим списком."""
    source = _sources()
    excluded = _excluded_classes()
    assert excluded, 'список виключень порожній -- розбір селектора зламався'

    orphans = [cls for cls in excluded
               if not re.search(r'(?<![A-Za-z0-9_-])' + re.escape(cls)
                                + r'(?![A-Za-z0-9_-])', source)]

    assert not orphans, (
        'у списку виключень molecular-background.css є імена, яких більше '
        'немає в коді: ' + ', '.join(sorted(orphans)) + '. '
        'Найімовірніше, компонент перейменували, а список не оновили -- '
        'тоді його оверлей зараз отримує position:relative замість fixed '
        'і не показується. Оновіть :not() на нове ім\'я класу.'
    )


def test_main_outranks_footer():
    """`main` мусить мати власний z-index, вищий за спільне правило.

    `main` і `footer` -- прямі діти body. Поки обидва мали z-index:1,
    футер як пізніший сусід лягав поверх усього вмісту main, а fixed-
    елементи всередині main не могли з-під нього вибратись: їхній
    z-index замкнений контекстом накладання, який створює саме те
    правило. Так липка CTA курсу ховалась під футером на мобільному.

    Тому main виведено з переліку і має власне правило. Якщо його
    повернуть під спільне -- CTA знову перестане натискатись унизу
    сторінки, і жоден інший тест цього не помітить.
    """
    text = CSS_FILE.read_text(encoding='utf-8')

    shared = _RULE.search(text)
    assert ':not(main)' in shared.group(1), (
        'main більше не виключений зі спільного правила body > *:not(...) -- '
        'він знову отримає z-index:1 нарівні з футером, і футер '
        'перекриватиме липку CTA курсу.'
    )

    own = re.search(r'body\s*>\s*main\s*\{([^}]*)\}', text)
    assert own, 'немає власного правила `body > main` із підвищеним z-index'
    z_index = re.search(r'z-index:\s*(\d+)', own.group(1))
    assert z_index and int(z_index.group(1)) > 1, (
        'у `body > main` z-index мусить бути більший за 1 (значення '
        'спільного правила), інакше футер знову перекриє вміст main.'
    )


def test_lightbox_is_excluded():
    """Лайтбокс -- body-level fixed-оверлей, отже мусить бути у списку.

    Окремо від загальної перевірки: саме на ньому список і розійшовся з
    кодом, і саме його регресія найдорожча -- компонент спільний для
    трьох розділів сайту.
    """
    assert 'iprm-lightbox' in _excluded_classes(), (
        '.iprm-lightbox немає у виключеннях molecular-background.css -- '
        'оверлей лайтбокса отримає position:relative і не відкриється '
        'у блозі, галереї курсу і регаліях тренера.'
    )
