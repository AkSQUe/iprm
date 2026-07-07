/* admin-materials.js -- інтерактив сторінки резервування матеріалів MM Medic.

   Прогресивне покращення: без JS сторінка повністю робоча (пошук/множник --
   зручності; підрахунок суми дублює серверний). Vanilla JS, без залежностей.
   Сортування колонок і мобільні картки надаються глобальними
   admin-table-sort.js / admin-table-cards.js. */
(function () {
  'use strict';

  function num(v) {
    var n = parseInt(String(v == null ? '' : v).replace(',', '.'), 10);
    return isNaN(n) ? 0 : n;
  }

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  ready(function () {
    // Print button (picking list) -- works on any page with [data-print].
    var printBtn = document.querySelector('[data-print]');
    if (printBtn) {
      printBtn.addEventListener('click', function () { window.print(); });
    }

    var table = document.getElementById('materialsTable');
    if (!table) return;

    var rows = Array.prototype.slice.call(table.querySelectorAll('tr[data-row]'));
    var countEl = document.getElementById('materialsCount');
    var costEl = document.getElementById('materialsCost');

    // ---- summary (кількість обраних позицій + орієнтовна вартість) ----
    function recalc() {
      var count = 0;
      var cost = 0;
      rows.forEach(function (tr) {
        var input = tr.querySelector('input[data-qty]');
        if (!input) return;
        var qty = num(input.value);
        if (qty > 0) count++;
        var price = parseFloat(input.getAttribute('data-price'));
        if (qty > 0 && !isNaN(price)) cost += price * qty;

        // Підсвітка перевищення наявного залишку.
        var availAttr = input.getAttribute('data-available');
        var over = availAttr !== '' && availAttr != null && qty > num(availAttr);
        input.classList.toggle('is-over', !!over);
      });
      if (countEl) countEl.textContent = String(count);
      if (costEl) costEl.textContent = cost.toFixed(2);
    }

    table.addEventListener('input', function (e) {
      if (e.target && e.target.matches('input[data-qty]')) recalc();
    });
    recalc();

    // ---- пошук по назві/артикулу ----
    var search = document.getElementById('materialsSearch');
    if (search) {
      search.addEventListener('input', function () {
        var q = search.value.trim().toLowerCase();
        rows.forEach(function (tr) {
          var name = tr.getAttribute('data-name') || '';
          var sku = (tr.getAttribute('data-sku') || '').toLowerCase();
          var hit = !q || name.indexOf(q) !== -1 || sku.indexOf(q) !== -1;
          tr.style.display = hit ? '' : 'none';
        });
      });
    }

    // ---- ×N: помножити всі кількості на множник ----
    var xnBtn = document.getElementById('materialsXnBtn');
    var xnInput = document.getElementById('materialsXn');
    if (xnBtn && xnInput) {
      xnBtn.addEventListener('click', function () {
        var factor = num(xnInput.value);
        if (factor < 1) return;
        rows.forEach(function (tr) {
          var input = tr.querySelector('input[data-qty]');
          if (!input) return;
          var base = num(input.value);
          if (base > 0) input.value = String(base * factor);
        });
        recalc();
      });
    }
  });
})();
