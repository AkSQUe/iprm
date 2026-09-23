"""Поведінка редактора сертифікатів-зображень (trainer-certificates-editor.js).

Як і test_certificates_editor_icon.py: jsdom у проєкті немає, тож РЕАЛЬНИЙ
файл виконується в Node через vm.runInContext у мінімальному DOM-стабі, а
сценарій (кліки, клавіші, відправка форми) відтворюється викликом зібраних
слухачів. Регекс по тексту довів би лише «рядок десь є», а не що редактор
справді робить.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / 'app' / 'static' / 'js' / 'trainer-certificates-editor.js'

_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');

function makeEl(tag) {
  const el = {
    tagName: tag, attrs: {}, className: '', children: [], listeners: {},
    style: {}, dataset: {}, value: '', textContent: '', disabled: false,
    files: [], form: null,
    setAttribute(k, v) { this.attrs[k] = v; if (k === 'class') this.className = v; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(evt, fn) { (this.listeners[evt] = this.listeners[evt] || []).push(fn); },
    fire(evt, extra) {
      const e = Object.assign({ preventDefault() { this.defaultPrevented = true; },
                                defaultPrevented: false, returnValue: undefined }, extra || {});
      (this.listeners[evt] || []).forEach((fn) => fn(e));
      return e;
    },
    focus() { focused.el = this; },
    classList: { add() {}, remove() {} },
  };
  Object.defineProperty(el, 'innerHTML', { set() { el.children = []; }, get() { return ''; } });
  return el;
}
const focused = { el: null };

const jsPath = process.argv[2];
const scenario = process.argv[3];

const form = makeEl('form');
const idMap = {
  'regalia-cert-field': makeEl('input'),
  'regalia-certs-grid': makeEl('div'),
  'regalia-cert-file': makeEl('input'),
  'regalia-cert-add': makeEl('button'),
};
const field = idMap['regalia-cert-field'];
field.form = form;
field.value = JSON.stringify([
  { url: '/media/a.webp', caption: 'A' },
  { url: '/media/b.webp', caption: 'B' },
  { url: '/media/c.webp', caption: 'C' },
]);
field.setAttribute('data-upload-url', '/x/upload');

const document = {
  listeners: {}, createElement: makeEl,
  getElementById: (id) => idMap[id] || null,
  querySelector: () => null, querySelectorAll: () => [],
  addEventListener(evt, fn) { (this.listeners[evt] = this.listeners[evt] || []).push(fn); },
};
const windowListeners = {};
const window = {
  addEventListener(evt, fn) { (windowListeners[evt] = windowListeners[evt] || []).push(fn); },
};
if (scenario === 'i18n') {
  window.iprmI18n = { t(k) { return 'T:' + k; } };
}
function fireWindow(evt) {
  const e = { preventDefault() { this.defaultPrevented = true; }, defaultPrevented: false,
              returnValue: undefined };
  (windowListeners[evt] || []).forEach((fn) => fn(e));
  return e;
}

const sandbox = { document, window, alert: () => {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(jsPath, 'utf8'), sandbox);
(document.listeners['DOMContentLoaded'] || []).forEach((fn) => fn());

const grid = idMap['regalia-certs-grid'];
const captions = () => JSON.parse(field.value).map((c) => c.caption);
// Кнопки картки: шукаємо за класом, а не за позицією -- порядок дітей у
// розмітці не контракт.
function findByClass(node, cls, out) {
  out = out || [];
  if ((node.className || '').split(' ').indexOf(cls) !== -1) out.push(node);
  (node.children || []).forEach((c) => findByClass(c, cls, out));
  return out;
}

const out = {};
if (scenario === 'dirty') {
  out.cleanPrevented = fireWindow('beforeunload').defaultPrevented;
  const cap = findByClass(grid, 'regalia-cert__cap')[0];
  cap.value = 'Нове';
  cap.fire('input');
  out.dirtyPrevented = fireWindow('beforeunload').defaultPrevented;
  form.fire('submit');
  out.afterSubmitPrevented = fireWindow('beforeunload').defaultPrevented;
} else if (scenario === 'keyboard') {
  const down = findByClass(grid, 'regalia-cert__move-down')[0];
  out.hasButtons = !!down && findByClass(grid, 'regalia-cert__move-up').length === 3;
  if (down) {
    out.downLabel = down.attrs['aria-label'] || null;
    down.fire('click');
    out.afterDown = captions();
    // Фокус -- на кнопці «нижче» тієї самої картки, що тепер друга.
    const secondDown = findByClass(grid, 'regalia-cert__move-down')[1];
    out.focusFollowsCard = focused.el === secondDown;
    const upOfLast = findByClass(grid, 'regalia-cert__move-up')[2];
    upOfLast.fire('click');
    out.afterUp = captions();
    out.firstUpDisabled = findByClass(grid, 'regalia-cert__move-up')[0].disabled;
    out.lastDownDisabled = findByClass(grid, 'regalia-cert__move-down')[2].disabled;
  }
} else if (scenario === 'i18n') {
  const rm = findByClass(grid, 'regalia-cert__remove')[0];
  const cap = findByClass(grid, 'regalia-cert__cap')[0];
  out.removeTitle = rm.attrs.title;
  out.capPlaceholder = cap.attrs.placeholder;
}
console.log(JSON.stringify(out));
"""

pytestmark = pytest.mark.skipif(
    shutil.which('node') is None,
    reason='node недоступний у цьому середовищі -- тест поведінки JS пропущено',
)


def _run(tmp_path, scenario):
    harness = tmp_path / 'probe.js'
    harness.write_text(_HARNESS, encoding='utf-8')
    result = subprocess.run(
        ['node', str(harness), str(JS_PATH), scenario],
        capture_output=True, encoding='utf-8', check=True, timeout=15,
    )
    return json.loads(result.stdout)


def test_leaving_with_unsaved_changes_is_guarded(tmp_path):
    """Незбережена зміна -> попередження при виході; відправка форми його знімає.

    Без змін попередження бути не має: воно лякало б тренера, який лише
    переглядав свої сертифікати.
    """
    out = _run(tmp_path, 'dirty')
    assert out['cleanPrevented'] is False
    assert out['dirtyPrevented'] is True
    assert out['afterSubmitPrevented'] is False


def test_visible_strings_go_through_public_dictionary(tmp_path):
    """У кабінеті словник i18n.js є -- рядки редактора мусять іти через нього,
    інакше тренер з ru/en бачить українські підказки."""
    out = _run(tmp_path, 'i18n')
    assert out['removeTitle'] == 'T:Видалити'
    assert out['capPlaceholder'] == 'T:Підпис (необовʼязково)'


def test_certificates_can_be_reordered_from_keyboard(tmp_path):
    """Перетягування -- лише мишею; кнопки «вище/нижче» дають те саме
    клавіатурі й скрінрідеру, а фокус не втрачається після перестановки."""
    out = _run(tmp_path, 'keyboard')
    assert out['hasButtons'] is True
    assert out['downLabel'] == 'Перемістити нижче'
    assert out['afterDown'] == ['B', 'A', 'C']
    assert out['focusFollowsCard'] is True
    assert out['afterUp'] == ['B', 'C', 'A']
    assert out['firstUpDisabled'] is True
    assert out['lastDownDisabled'] is True
