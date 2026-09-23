"""Дефект Б (візуальна перевірка, раунд 2): кнопка видалення сертифіката
показувала буквальний текст "close" у кабінеті тренера.

Причина: trainer-certificates-editor.js рендерить іконку через
window.msGlyph(name) із фолбеком на СИРУ НАЗВУ, а msGlyph/IPRM_ICONS
оголошені лише в admin/base_admin.html (партіал partials/_icon_font.html,
що вантажить сам шрифт, теж підключений лише звідти). Кабінет тренера
розширює base.html, де цих глобалів нема -- спільний редактор ніс
залежність, задоволену лише на одному з двох своїх споживачів.

Тестів на поведінку JS у проєкті немає (немає ні Jest, ні jsdom) -- Node тут
є (перевірено `node --version`), тож поведінку `icon()` перевіряємо
запуском РЕАЛЬНОГО файлу в мінімальному DOM-стабі через vm.runInContext,
а не регексом по тексту: регекс довів би лише "рядок десь є", а не що саме
рендериться в DOM для двох сценаріїв (адмінка з msGlyph і кабінет без
нього). Проходи: `pathlib`, `subprocess`, `node` зі стандартної поставки.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / 'app' / 'static' / 'js' / 'trainer-certificates-editor.js'

# Мінімальний DOM-стаб: лише те, що реально вживає mount()/render()/icon() --
# createElement/getElementById/querySelector(All)/addEventListener,
# setAttribute+className (el() кладе 'class' напряму в className, решту --
# через setAttribute), appendChild, classList-заглушка. DOMContentLoaded не
# спрацьовує сам у vm-контексті -- слухач перехоплюємо і викликаємо вручну.
_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');

function makeEl(tag) {
  return {
    tagName: tag,
    attrs: {},
    className: '',
    children: [],
    listeners: {},
    style: {},
    dataset: {},
    value: '',
    textContent: '',
    disabled: false,
    files: [],
    setAttribute(k, v) { this.attrs[k] = v; if (k === 'class') this.className = v; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(evt, fn) { (this.listeners[evt] = this.listeners[evt] || []).push(fn); },
    classList: { add() {}, remove() {} },
  };
}

const jsPath = process.argv[2];
const withGlyph = process.argv[3] === 'with-glyph';

const idMap = {};
idMap['regalia-cert-field'] = makeEl('input');
idMap['regalia-cert-field'].value = JSON.stringify([{ url: '/media/a.webp', caption: 'C' }]);
idMap['regalia-cert-field'].setAttribute('data-upload-url', '/x/upload');
idMap['regalia-certs-grid'] = makeEl('div');
idMap['regalia-cert-file'] = makeEl('input');
idMap['regalia-cert-add'] = makeEl('button');

const document = {
  listeners: {},
  createElement: makeEl,
  getElementById: (id) => idMap[id] || null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener(evt, fn) { (this.listeners[evt] = this.listeners[evt] || []).push(fn); },
};

// addEventListener -- редактор вішає на window попередження про незбережені
// зміни (beforeunload); у браузері він є завжди.
const window = { addEventListener() {} };
if (withGlyph) {
  // Заглушка адмінського window.msGlyph (справжній -- у base_admin.html):
  // повертає розпізнаваний рядок, щоб довести, що ЦЕЙ шлях і досі
  // використовується, коли глобал є -- адмінська поведінка не зачеплена.
  window.msGlyph = function (name) { return 'CODEPOINT:' + name; };
}

const sandbox = { document, window, alert: () => {} };
vm.createContext(sandbox);
const src = fs.readFileSync(jsPath, 'utf8');
vm.runInContext(src, sandbox);

(document.listeners['DOMContentLoaded'] || []).forEach((fn) => fn());

const grid = idMap['regalia-certs-grid'];
const certDiv = grid.children[0];
const thumb = certDiv.children[0];
const rmBtn = thumb.children[1];
const iconSpan = rmBtn.children[0];
console.log(JSON.stringify({
  iconText: iconSpan.textContent,
  rmTitle: rmBtn.attrs.title || null,
}));
"""

pytestmark = pytest.mark.skipif(
    shutil.which('node') is None,
    reason='node недоступний у цьому середовищі -- тест поведінки JS пропущено',
)


def _run(tmp_path, with_glyph):
    harness = tmp_path / 'probe.js'
    harness.write_text(_HARNESS, encoding='utf-8')
    result = subprocess.run(
        ['node', str(harness), str(JS_PATH), 'with-glyph' if with_glyph else 'without-glyph'],
        capture_output=True, encoding='utf-8', check=True, timeout=15,
    )
    return json.loads(result.stdout)


def test_remove_button_icon_has_fallback_without_admin_glyph(tmp_path):
    """Кабінет тренера: window.msGlyph немає (base.html його не задає).

    Раніше фолбек показував сиру назву 'close' буквальним текстом у кнопці
    видалення -- саме той дефект, що знайшла візуальна перевірка. Символ
    "×" -- та сама заглушка, що й у .iprm-lightbox__close (lightbox.js),
    вона не залежить від жодного шрифту.
    """
    out = _run(tmp_path, with_glyph=False)
    assert out['iconText'] != 'close', (
        'кнопка видалення показує сиру назву іконки замість символу -- '
        'редактор досі залежить від window.msGlyph, якого в кабінеті нема'
    )
    assert out['iconText'] == '×'


def test_remove_button_icon_still_uses_admin_glyph_when_present(tmp_path):
    """Адмінка: window.msGlyph є -- поведінка мусить лишитись, як була."""
    out = _run(tmp_path, with_glyph=True)
    assert out['iconText'] == 'CODEPOINT:close'


def test_remove_button_has_accessible_title_in_both_scenarios(tmp_path):
    """Незалежно від того, яку іконку показує кнопка, у неї має бути
    зрозумілий текст для скрінрідера."""
    for with_glyph in (False, True):
        out = _run(tmp_path, with_glyph=with_glyph)
        assert out['rmTitle']
