/* admin-table-cards.js -- адаптив таблиць у картки на мобільних.

   На вузьких екранах .admin-table рендериться картками (CSS у admin.css).
   Щоб у картці перед кожним значенням стояла назва поля, копіюємо текст
   заголовків <thead> у data-label кожної <td> (CSS показує його через
   td::before). Працює для всіх адмін-таблиць без правок шаблонів.

   Прогресивне покращення: без JS картки все одно стекаються вертикально,
   просто без міток-заголовків. */
(function () {
  'use strict';

  function labelize(table) {
    var heads = table.querySelectorAll('thead th');
    if (!heads.length) return;
    var labels = Array.prototype.map.call(heads, function (th) {
      return (th.textContent || '').trim();
    });
    var rows = table.querySelectorAll('tbody tr');
    Array.prototype.forEach.call(rows, function (tr) {
      var cells = tr.children;
      if (cells.length <= 1) return; // empty-state / colspan-рядок
      for (var i = 0; i < cells.length; i++) {
        var cell = cells[i];
        if (cell.tagName !== 'TD' || cell.hasAttribute('data-label')) continue;
        var label = labels[i] || '';
        if (label) cell.setAttribute('data-label', label);
      }
    });
  }

  function run() {
    /* Сітка (--grid) на мобільному лишається таблицею, мітки їй не потрібні. */
    document.querySelectorAll('table.admin-table:not(.admin-table--grid)').forEach(labelize);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
})();
