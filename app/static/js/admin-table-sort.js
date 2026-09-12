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

  /* Рядок, у якому комірок МЕНШЕ, ніж колонок, -- це не запис, а продовження
     запису над ним: примітка на всю ширину через colspan (причина невдачі
     копіювання, пояснення до рядка). Сортування мусить нести його разом із
     своїм рядком -- інакше примітка лишається там, де стояла, і опиняється
     під чужим записом, тобто сторінка починає приписувати чужу помилку
     сусідній копії. Ознака та сама, якою колспан-рядки визначає
     admin-table-cards.js, -- кількість комірок. */
  function groupRows(tbody, columns) {
    var groups = [];
    for (var i = 0; i < tbody.rows.length; i++) {
      var row = tbody.rows[i];
      if (groups.length && row.cells.length < columns) {
        groups[groups.length - 1].extra.push(row);
      } else {
        groups.push({ row: row, extra: [] });
      }
    }
    return groups;
  }

  function sortBy(table, tbody, idx, th, dir) {
    var columns = table.tHead.rows[0].cells.length;
    // Стабільне сортування: зберігаємо початковий індекс як tie-breaker.
    var decorated = groupRows(tbody, columns).map(function (group, i) {
      var cell = group.row.cells[idx];
      return { group: group, key: extract(cell ? cell.textContent : ''), i: i };
    });
    decorated.sort(function (x, y) {
      var c = compare(x.key, y.key);
      return (dir === 'desc' ? -c : c) || (x.i - y.i);
    });
    var frag = document.createDocumentFragment();
    decorated.forEach(function (item) {
      frag.appendChild(item.group.row);
      item.group.extra.forEach(function (row) { frag.appendChild(row); });
    });
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
    var headers = table.tHead.rows[0].cells;
    // Рахуємо ЗАПИСИ, а не рядки: таблиця з одного запису й примітки під ним
    // дала б два рядки, і заголовки отримували б стрілку сортування даремно.
    if (groupRows(tbody, headers.length).length < 2) return;

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
