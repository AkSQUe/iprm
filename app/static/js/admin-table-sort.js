/* admin-table-sort.js -- сортування рядків адмін-таблиць по кліку на заголовок.

   Працює з усіма <table class="admin-table">. Колонки з інтерактивним
   вмістом (форми, select, кнопки -- статус, дії) автоматично пропускаються.
   Тип значення визначається евристично: дата (дд.мм.рррр), число, текст.
   Клієнтський сорт без бекенду. Vanilla JS. */
(function () {
  'use strict';

  function extract(text) {
    var s = (text || '').trim();
    // Дата дд.мм.рррр [гг:хх]
    var d = s.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[ ,]+(\d{1,2}):(\d{2}))?$/);
    if (d) {
      return new Date(+d[3], +d[2] - 1, +d[1], +(d[4] || 0), +(d[5] || 0)).getTime();
    }
    // Число (прибираємо пробіли, валюту, №, #, %; кому -> крапку)
    var cleaned = s.replace(/[\s ₴$€%№#]/g, '').replace(',', '.');
    if (cleaned !== '' && /\d/.test(cleaned) && !isNaN(cleaned)) {
      return parseFloat(cleaned);
    }
    return s.toLowerCase();
  }

  function compare(a, b) {
    if (typeof a === 'number' && typeof b === 'number') return a - b;
    return String(a).localeCompare(String(b), 'uk');
  }

  function columnInteractive(tbody, idx) {
    for (var i = 0; i < tbody.rows.length; i++) {
      var cell = tbody.rows[i].cells[idx];
      if (cell && cell.querySelector('form, select, button, input, .admin-table__actions')) {
        return true;
      }
    }
    return false;
  }

  function sortBy(table, tbody, idx, th, dir) {
    var rows = Array.prototype.slice.call(tbody.rows);
    // Стабільне сортування: зберігаємо початковий індекс як tie-breaker.
    var decorated = rows.map(function (row, i) {
      var cell = row.cells[idx];
      return { row: row, key: extract(cell ? cell.textContent : ''), i: i };
    });
    decorated.sort(function (x, y) {
      var c = compare(x.key, y.key);
      return (dir === 'desc' ? -c : c) || (x.i - y.i);
    });
    var frag = document.createDocumentFragment();
    decorated.forEach(function (item) { frag.appendChild(item.row); });
    tbody.appendChild(frag);

    // Індикатори на заголовках.
    var headers = table.tHead.rows[0].cells;
    for (var h = 0; h < headers.length; h++) {
      headers[h].classList.remove('is-asc', 'is-desc');
    }
    th.classList.add(dir === 'desc' ? 'is-desc' : 'is-asc');
  }

  function initTable(table) {
    if (!table.tHead || !table.tHead.rows.length || !table.tBodies.length) return;
    var tbody = table.tBodies[0];
    if (tbody.rows.length < 2) return; // нема чого сортувати
    var headers = table.tHead.rows[0].cells;

    Array.prototype.forEach.call(headers, function (th, idx) {
      if (th.hasAttribute('data-no-sort')) return;
      if (columnInteractive(tbody, idx)) return;
      th.classList.add('admin-th--sortable');
      th.addEventListener('click', function () {
        var dir = (table.__sortCol === idx && table.__sortDir === 'asc') ? 'desc' : 'asc';
        table.__sortCol = idx;
        table.__sortDir = dir;
        sortBy(table, tbody, idx, th, dir);
      });
    });
  }

  function init() {
    document.querySelectorAll('table.admin-table').forEach(initTable);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
