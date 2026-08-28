"""Атрибут [hidden] має реально ховати елемент.

Браузерне правило [hidden] { display: none } живе в UA-стилях, тож будь-який
власний `display: flex` на компоненті його перебиває. JS ставить hidden,
а елемент лишається на екрані.

У проєкті на це наступали шість разів: confirm-action, form-progress,
розклад курсу, медіа-пікер, картка курсу -- залатані окремими правилами;
банер міста на реєстрації і липка панель курсу на мобільному -- ні.
Тепер інваріант тримає одне глобальне правило в common.css.

Ці тести статичні: HTML-тести бачать лише атрибут у розмітці, а не те, чи
браузер справді сховає елемент, -- саме тому попередня перевірка нічого
не спіймала.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / 'app' / 'static'
CSS_DIR = STATIC / 'css'
JS_DIR = STATIC / 'js'


def _css(name):
    return (CSS_DIR / name).read_text(encoding='utf-8')


def _css_rules(name):
    """CSS без коментарів: інакше пошук правил чіпляє текст пояснень."""
    return re.sub(r'/\*.*?\*/', '', _css(name), flags=re.DOTALL)


def test_global_hidden_rule_exists():
    """Без цього правила кожен flex-компонент треба глушити окремо."""
    rule = re.search(r'\[hidden\]\s*\{[^}]*\}', _css_rules('common.css'))
    assert rule, 'у common.css немає глобального правила [hidden]'
    body = rule.group(0)
    assert 'display' in body and 'none' in body
    assert '!important' in body, (
        'без !important правило програє авторському display на компоненті'
    )


def test_hidden_rule_is_not_scoped():
    """Правило має бути глобальним, а не під якимось контейнером."""
    assert re.search(r'(^|\n)\[hidden\]\s*\{', _css('common.css')), \
        'правило [hidden] прив\'язане до селектора-предка'


def test_common_css_is_loaded_everywhere():
    base = (Path(__file__).resolve().parents[2] / 'app' / 'templates'
            / 'base.html').read_text(encoding='utf-8')
    assert "filename='css/common.css'" in base


# Компоненти, які JS ховає атрибутом hidden і які мають власний display.
# Тримаємо перелік явним: якщо додасться новий, тест не впаде сам собою,
# але глобальне правило його вже покриває.
TOGGLED_COMPONENTS = [
    ('registration.css', 'reg-location-callout'),
    ('registration.css', 'reg-sticky-cta'),
    # Переїхав із courses.css: компонент спільний для сторінок очного
    # й онлайн-курсу, тому живе в course-landing.css.
    ('course-landing.css', 'iprm-sticky-cta'),
]


@pytest.mark.parametrize('css_file, cls', TOGGLED_COMPONENTS)
def test_toggled_component_has_display_and_relies_on_global_rule(css_file, cls):
    """Фіксуємо причину: у цих компонентів є власний display, тобто без
    глобального правила атрибут hidden на них не діяв би."""
    text = _css_rules(css_file)
    block = re.search(rf'\.{re.escape(cls)}\s*\{{[^}}]*\}}', text)
    assert block, f'{cls} не знайдено в {css_file}'
    # display оголошено або в базовому правилі, або в media-query
    has_display = 'display' in block.group(0) or re.search(
        rf'@media[^{{]*\{{[^}}]*\.{re.escape(cls)}\s*\{{[^}}]*display', text)
    assert has_display, f'{cls}: display не задано -- тест застарів'


def test_js_toggles_hidden_on_registration_blocks():
    """Зв'язок JS -> атрибут: якщо перестануть ставити hidden, CSS не
    допоможе."""
    js = (JS_DIR / 'reg-tariffs.js').read_text(encoding='utf-8')
    assert 'data-presence-confirm' in js
    assert '.hidden' in js
