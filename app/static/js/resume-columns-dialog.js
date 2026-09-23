/* Наповнення прихованих id тренерів перед відкриттям спільного діалогу
   колонок резюме (partials/_resume_columns_dialog.html). Показ і ховання
   самого вікна робить компонент .modal (modal.js) -- тут лише джерело id,
   яке різне на двох сторінках: явний перелік на кнопці сторінки
   проведення (data-trainer-ids) чи позначені рядки в списку тренерів
   (input[name="trainer_ids"]:checked).

   Слухач ставимо на фазі перехоплення (capture: true). modal.js вішає
   свій клік-обробник на document у фазі спливання -- якби покластись на
   порядок підключення <script>, відкриття вікна випереджало б заповнення
   id при іншому порядку тегів. Фаза перехоплення на document завжди
   відпрацьовує РАНІШЕ фази спливання незалежно від порядку скриптів, тож
   тут же можна і покласти id, і -- коли їх немає -- зупинити подію, не
   дозволивши modal.js відкрити порожній діалог. */
(function () {
  'use strict';

  var DIALOG_ID = 'resume-columns-dialog';

  document.addEventListener('click', function (event) {
    var opener = event.target.closest('[data-modal-open="' + DIALOG_ID + '"]');
    if (!opener) { return; }

    var idsBox = document.getElementById('resume-columns-ids');
    if (!idsBox) { return; }

    var raw = opener.getAttribute('data-trainer-ids') || '';
    var ids = raw.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    if (!ids.length) {
      // Список тренерів: явного переліку на кнопці немає -- беремо
      // позначені рядки таблиці.
      ids = Array.prototype.slice
        .call(document.querySelectorAll('input[name="trainer_ids"]:checked'))
        .map(function (el) { return el.value; });
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
