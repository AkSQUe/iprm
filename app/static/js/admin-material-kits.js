/* Комплекти матеріалів (admin/material_kit_edit.html): форма додавання
   позиції з каталогу MM Medic. `name_snapshot` пишеться на МОМЕНТ
   додавання (app/models/material_kit.py), тож при виборі позиції зі
   списку копіюємо назву в приховане поле разом із sku -- сервер уже
   має її, а не шукає в каталозі вдруге. */
(function () {
  'use strict';

  var select = document.getElementById('kitItemSku');
  var hidden = document.getElementById('kitItemNameSnapshot');
  if (!select || !hidden) return;

  function syncSnapshot() {
    var option = select.options[select.selectedIndex];
    hidden.value = option ? (option.getAttribute('data-name') || '') : '';
  }

  select.addEventListener('change', syncSnapshot);
  syncSnapshot();
})();
