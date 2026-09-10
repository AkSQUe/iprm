/* Прев'ю блоку «Цільова аудиторія» у формі заходу.
 *
 * Показує назви спеціальностей, які підуть на сторінку заходу самі, і
 * оновлює їх одразу після зміни вибору -- щоб редактор бачив, що вже
 * виведеться, і не переписував те саме в поле додаткового опису.
 *
 * Прогресивне покращення: блок уже відрендерив сервер зі збереженого
 * стану, скрипт лише підтримує його свіжим. Джерело правди -- сам
 * <select> спеціальностей (див. admin-multiselect.js), тому слухаємо
 * його change, а не внутрішні події компонента.
 */
(function () {
  'use strict';

  function selectedLabels(select) {
    return Array.prototype.filter.call(select.options, function (option) {
      return option.selected;
    }).map(function (option) {
      return option.textContent.trim();
    });
  }

  function render(box, labels) {
    box.textContent = '';
    if (!labels.length) {
      var empty = document.createElement('span');
      empty.className = 'admin-audience-preview__empty';
      empty.textContent = box.dataset.audiencePreviewEmpty || '';
      box.appendChild(empty);
      return;
    }
    labels.forEach(function (label) {
      var chip = document.createElement('span');
      chip.className = 'iprm-tag iprm-tag--inset';
      chip.textContent = label;
      box.appendChild(chip);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    Array.prototype.forEach.call(
      document.querySelectorAll('[data-audience-preview]'),
      function (box) {
        var select = document.getElementById(box.dataset.audiencePreviewSource);
        if (!select) { return; }
        // Порядок чіпів -- порядок <option> у списку, а він уже зібраний за
        // номенклатурою (specialties.choices); той самий порядок дає й
        // сторінка заходу.
        select.addEventListener('change', function () {
          render(box, selectedLabels(select));
        });
      }
    );
  });
})();
