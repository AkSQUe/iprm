/* PDF-резюме тренерів в адмінці: джерело id для спільного діалогу колонок
   (partials/_resume_columns_dialog.html) і вибір тренерів у списку.

   Показ і ховання самого вікна робить компонент .modal (modal.js) -- тут
   лише звідки беруться id. На сторінці проведення -- явний перелік на
   кнопці (data-trainer-ids). У списку тренерів -- позначені рядки, і цей
   вибір переживає пошук і фільтр: список фільтрується перезавантаженням
   сторінки, і без збереження адмін губив би позначених щоразу, як шукав
   наступного. Вибір лежить у sessionStorage (лише ця вкладка, лише цей
   адмін); поруч із кнопкою -- лічильник і «Скинути», бо позначений, але
   відфільтрований тренер на екрані не видно, а в документ він потрапить.

   Слухач кліку ставимо на фазі перехоплення (capture: true). modal.js
   вішає свій клік-обробник на document у фазі спливання -- фаза
   перехоплення завжди відпрацьовує РАНІШЕ незалежно від порядку скриптів,
   тож тут можна і покласти id, і -- коли їх немає -- зупинити подію, не
   давши modal.js відкрити порожній діалог. */
(function () {
  'use strict';

  var DIALOG_ID = 'resume-columns-dialog';
  var STORAGE_KEY = 'iprm.resume.selectedTrainers';
  // Набір колонок -- один на адміна й обидві сторінки: пакет документів
  // до реєстру зазвичай той самий від подання до подання, і щоразу знімати
  // й ставити ті самі галочки -- зайва робота. localStorage, а не session:
  // це налаштування, а не поточна робота.
  var COLUMNS_KEY = 'iprm.resume.columns';

  function readStored() {
    try {
      var raw = window.sessionStorage.getItem(STORAGE_KEY);
      var parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.map(String) : [];
    } catch (e) {
      return [];
    }
  }

  function writeStored(ids) {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
    } catch (e) {
      /* приватний режим чи заборонене сховище -- вибір живе до перезавантаження */
    }
  }

  var selected = [];

  function rowBoxes() {
    return Array.prototype.slice.call(document.querySelectorAll('input[name="trainer_ids"]'));
  }

  function refreshCounter() {
    var counter = document.getElementById('resume-selected-count');
    var clear = document.querySelector('[data-resume-clear]');
    if (counter) {
      counter.textContent = selected.length ? 'Обрано: ' + selected.length : '';
      counter.hidden = !selected.length;
    }
    if (clear) clear.hidden = !selected.length;
    var all = document.querySelector('[data-resume-select-all]');
    if (all) {
      var boxes = rowBoxes();
      all.checked = boxes.length > 0 && boxes.every(function (b) { return b.checked; });
    }
  }

  function setSelected(id, on) {
    var i = selected.indexOf(id);
    if (on && i === -1) selected.push(id);
    if (!on && i !== -1) selected.splice(i, 1);
  }

  function initSelection() {
    var boxes = rowBoxes();
    if (!boxes.length) return;
    selected = readStored();
    boxes.forEach(function (box) {
      box.checked = selected.indexOf(String(box.value)) !== -1;
      box.addEventListener('change', function () {
        setSelected(String(box.value), box.checked);
        writeStored(selected);
        refreshCounter();
      });
    });
    var all = document.querySelector('[data-resume-select-all]');
    if (all) {
      all.addEventListener('change', function () {
        rowBoxes().forEach(function (box) {
          box.checked = all.checked;
          setSelected(String(box.value), all.checked);
        });
        writeStored(selected);
        refreshCounter();
      });
    }
    var clear = document.querySelector('[data-resume-clear]');
    if (clear) {
      clear.addEventListener('click', function () {
        selected = [];
        writeStored(selected);
        rowBoxes().forEach(function (box) { box.checked = false; });
        refreshCounter();
      });
    }
    refreshCounter();
  }

  function columnBoxes() {
    return Array.prototype.slice.call(document.querySelectorAll('input[name="columns"]'));
  }

  function initColumns() {
    var boxes = columnBoxes();
    var form = document.getElementById('resume-columns-form');
    if (!boxes.length || !form) return;
    var saved = null;
    try {
      var raw = window.localStorage.getItem(COLUMNS_KEY);
      saved = raw ? JSON.parse(raw) : null;
    } catch (e) {
      saved = null;
    }
    // Колонки, яких у збереженому наборі нема на цій сторінці (інше право
    // доступу), просто пропускаються; порожній збережений набір не
    // застосовуємо -- сервер однаково підставив би типові.
    if (Array.isArray(saved) && saved.length) {
      boxes.forEach(function (box) { box.checked = saved.indexOf(box.value) !== -1; });
    }
    form.addEventListener('submit', function () {
      var picked = columnBoxes().filter(function (b) { return b.checked; })
        .map(function (b) { return b.value; });
      if (!picked.length) return;
      try {
        window.localStorage.setItem(COLUMNS_KEY, JSON.stringify(picked));
      } catch (e) {
        /* сховище недоступне -- наступного разу будуть типові колонки */
      }
    });
  }

  document.addEventListener('DOMContentLoaded', initSelection);
  document.addEventListener('DOMContentLoaded', initColumns);

  document.addEventListener('click', function (event) {
    var opener = event.target.closest('[data-modal-open="' + DIALOG_ID + '"]');
    if (!opener) { return; }

    var idsBox = document.getElementById('resume-columns-ids');
    if (!idsBox) { return; }

    var raw = opener.getAttribute('data-trainer-ids') || '';
    var ids = raw.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    if (!ids.length) {
      // Список тренерів: явного переліку на кнопці немає -- беремо весь
      // збережений вибір, включно з тими, кого поточний пошук сховав.
      ids = selected.slice();
    }

    if (!ids.length) {
      event.stopPropagation();
      if (typeof window.iprmToast === 'function') {
        window.iprmToast('Оберіть хоча б одного тренера', 'error');
      } else {
        alert('Оберіть хоча б одного тренера');
      }
      return;
    }

    idsBox.innerHTML = '';
    ids.forEach(function (id) {
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'ids';
      input.value = id;
      idsBox.appendChild(input);
    });
  }, true);
})();
