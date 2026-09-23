"""Поведінка resume-columns-dialog.js: вибір тренерів для PDF-резюме.

Як і тести редактора сертифікатів: РЕАЛЬНИЙ файл у Node через
vm.runInContext у мінімальному DOM-стабі. Два «завантаження сторінки» з
одним спільним sessionStorage відтворюють те, що робить адмін: позначив
тренерів, пошукав (сторінка перезавантажилась з іншим набором рядків) і
відкрив діалог.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS_PATH = ROOT / 'app' / 'static' / 'js' / 'resume-columns-dialog.js'

_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
const scenario = process.argv[3];

function makeStorage() {
  const store = {};
  return {
    getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
    setItem(k, v) { store[k] = String(v); },
  };
}
const sessionStorage = makeStorage();
const localStorage = makeStorage();

function makeEl(tag, props) {
  const el = Object.assign({
    tagName: tag, attrs: {}, children: [], listeners: {}, hidden: false,
    checked: false, value: '', textContent: '', type: '', name: '',
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(evt, fn) { (this.listeners[evt] = this.listeners[evt] || []).push(fn); },
    fire(evt) { (this.listeners[evt] || []).forEach((fn) => fn({})); },
    closest() { return null; },
  }, props || {});
  Object.defineProperty(el, 'innerHTML', { set() { el.children = []; }, get() { return ''; } });
  return el;
}

// Одне «завантаження сторінки»: рядки таблиці з переданими id.
function loadPage(rowIds, columns) {
  const boxes = rowIds.map((id) => makeEl('input', { value: String(id), name: 'trainer_ids' }));
  // columns: [[key, типово позначена?], ...] -- як їх рендерить партіал.
  const columnBoxes = (columns || []).map(([key, on]) => makeEl('input', { value: key, checked: on }));
  const form = makeEl('form');
  const selectAll = makeEl('input');
  const clear = makeEl('button');
  const counter = makeEl('span');
  const idsBox = makeEl('div');
  const opener = makeEl('button', { attrs: { 'data-modal-open': 'resume-columns-dialog' } });
  const docListeners = {};
  const toasts = [];
  const document = {
    querySelectorAll(sel) {
      if (sel === 'input[name="trainer_ids"]') return boxes;
      if (sel === 'input[name="columns"]') return columnBoxes;
      return [];
    },
    querySelector(sel) {
      if (sel === '[data-resume-select-all]') return selectAll;
      if (sel === '[data-resume-clear]') return clear;
      return null;
    },
    getElementById(id) {
      if (id === 'resume-selected-count') return counter;
      if (id === 'resume-columns-ids') return idsBox;
      if (id === 'resume-columns-form') return form;
      return null;
    },
    createElement: (tag) => makeEl(tag),
    addEventListener(evt, fn) { (docListeners[evt] = docListeners[evt] || []).push(fn); },
  };
  const window = { sessionStorage, localStorage, iprmToast(m) { toasts.push(m); } };
  const sandbox = { document, window, alert() {} };
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);
  (docListeners['DOMContentLoaded'] || []).forEach((fn) => fn());
  function clickOpener() {
    let stopped = false;
    const event = {
      target: { closest: () => opener },
      stopPropagation() { stopped = true; },
    };
    (docListeners['click'] || []).forEach((fn) => fn(event));
    return { stopped, ids: idsBox.children.map((c) => c.value) };
  }
  return { boxes, selectAll, clear, counter, clickOpener, toasts, columnBoxes, form };
}

const out = {};
if (scenario === 'survives_search') {
  const first = loadPage([1, 2, 3]);
  first.boxes[0].checked = true; first.boxes[0].fire('change');
  first.boxes[2].checked = true; first.boxes[2].fire('change');
  // Пошук: інший набір рядків, позначені 1 і 3 на екрані не видно.
  const second = loadPage([2]);
  out.counter = second.counter.textContent;
  out.counterHidden = second.counter.hidden;
  out.secondBoxChecked = second.boxes[0].checked;
  out.opened = second.clickOpener();
} else if (scenario === 'select_all_and_clear') {
  const page = loadPage([4, 5]);
  page.selectAll.checked = true; page.selectAll.fire('change');
  out.afterAll = page.boxes.map((b) => b.checked);
  out.idsAfterAll = page.clickOpener().ids;
  page.clear.fire('click');
  out.afterClear = page.boxes.map((b) => b.checked);
  out.clearHidden = page.clear.hidden;
  const reloaded = loadPage([4, 5]);
  out.afterReload = reloaded.boxes.map((b) => b.checked);
} else if (scenario === 'remember_columns') {
  const columns = [['full_name', true], ['education', true], ['phone', false]];
  const first = loadPage([1], columns);
  first.columnBoxes[1].checked = false;   // зняв «Освіта»
  first.columnBoxes[2].checked = true;    // поставив «Телефон»
  first.form.fire('submit');
  const second = loadPage([1], columns);
  out.afterReload = second.columnBoxes.map((b) => b.checked);
  // Без права на колонку її на сторінці нема -- решта набору застосовується.
  const third = loadPage([1], [['full_name', true], ['education', true]]);
  out.withoutPhone = third.columnBoxes.map((b) => b.checked);
  const fresh = loadPage([1], columns.map(([k]) => [k, false]));
  fresh.form.fire('submit');                      // нічого не позначено
  const fourth = loadPage([1], columns);
  out.emptyNotSaved = fourth.columnBoxes.map((b) => b.checked);
} else if (scenario === 'nothing_selected') {
  const page = loadPage([6, 7]);
  const result = page.clickOpener();
  out.stopped = result.stopped;
  out.ids = result.ids;
  out.toasts = page.toasts;
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


def test_selection_survives_search_and_reaches_the_dialog(tmp_path):
    """Позначені тренери, яких новий пошук сховав, лишаються у виборі --
    і лічильник каже про них, і діалог їх бере."""
    out = _run(tmp_path, 'survives_search')
    assert out['counter'] == 'Обрано: 2'
    assert out['counterHidden'] is False
    assert out['secondBoxChecked'] is False
    assert out['opened']['stopped'] is False
    assert sorted(out['opened']['ids']) == ['1', '3']


def test_select_all_and_clear(tmp_path):
    out = _run(tmp_path, 'select_all_and_clear')
    assert out['afterAll'] == [True, True]
    assert sorted(out['idsAfterAll']) == ['4', '5']
    assert out['afterClear'] == [False, False]
    assert out['clearHidden'] is True
    assert out['afterReload'] == [False, False]


def test_empty_selection_does_not_open_dialog(tmp_path):
    out = _run(tmp_path, 'nothing_selected')
    assert out['stopped'] is True
    assert out['ids'] == []
    assert out['toasts'] == ['Оберіть хоча б одного тренера']


def test_last_column_set_is_remembered(tmp_path):
    """Набір колонок для подання зазвичай той самий -- діалог відкривається з
    останнім використаним, а не з типовим щоразу."""
    out = _run(tmp_path, 'remember_columns')
    assert out['afterReload'] == [True, False, True]
    assert out['withoutPhone'] == [True, False]
    # Порожній набір не перезаписує збережений.
    assert out['emptyNotSaved'] == [True, False, True]
