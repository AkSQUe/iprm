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

    // Copy-to-clipboard buttons (e.g. trainer link).
    document.querySelectorAll('[data-copy]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var text = btn.getAttribute('data-copy');
        var done = function () {
          var original = btn.innerHTML;
          btn.textContent = 'Скопійовано';
          setTimeout(function () { btn.innerHTML = original; }, 1500);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done, done);
        } else {
          var ta = document.createElement('textarea');
          ta.value = text; document.body.appendChild(ta); ta.select();
          try { document.execCommand('copy'); } catch (e) {}
          document.body.removeChild(ta); done();
        }
      });
    });

    var table = document.getElementById('materialsTable');
    if (!table) return;

    var form = document.getElementById('materialsForm');
    var mode = form ? form.getAttribute('data-mode') : '';
    var rows = Array.prototype.slice.call(table.querySelectorAll('tr[data-row]'));
    var countEl = document.getElementById('materialsCount');
    var costEl = document.getElementById('materialsCost');
    var changesEl = document.getElementById('materialsChanges');
    var usedEl = document.getElementById('materialsUsed');
    var returnsEl = document.getElementById('materialsReturns');
    var withdrawEl = document.getElementById('materialsWithdraw');
    var actualsMode = mode !== 'reserve' && mode !== 'edit';
    // Коригування вже списаного заходу: сервер рахує delta від ПОТОЧНОГО списаного
    // (quantity_actual), а не від зарезервованого. Порожнє поле = "без змін".
    var consumedMode = form ? form.getAttribute('data-consumed') === '1' : false;

    // ---- summary (кількість + вартість + попередження + diff редагування) ----
    function recalc() {
      var count = 0;
      var cost = 0;
      var changed = 0;
      var totalUsed = 0;
      var totalReturns = 0;
      var totalWithdraw = 0;
      rows.forEach(function (tr) {
        var input = tr.querySelector('input[data-qty]');
        if (!input) return;
        var qty = num(input.value);
        if (qty > 0) count++;
        var price = parseFloat(input.getAttribute('data-price'));
        if (qty > 0 && !isNaN(price)) cost += price * qty;

        // Повертається/довидається рахуємо від бази: у режимі коригування база --
        // поточне списане (data-actual), у першому списанні -- зарезервоване
        // (data-reserved). Порожнє поле = used == база (нічого не змінюється).
        if (actualsMode) {
          var baseAttr = input.getAttribute(consumedMode ? 'data-actual' : 'data-reserved');
          var hasBase = baseAttr !== '' && baseAttr != null;
          var base = num(baseAttr);
          var used = input.value.trim() === '' ? base : qty;
          var returns = hasBase ? Math.max(0, base - used) : 0;
          var withdraw = hasBase ? Math.max(0, used - base) : 0;
          totalUsed += used;
          totalReturns += returns;
          totalWithdraw += withdraw;
          var retEl = tr.querySelector('[data-returns]');
          if (retEl) {
            retEl.textContent = hasBase ? String(returns) : '—';
            retEl.classList.toggle('is-returning', hasBase && returns > 0);
          }
        }

        var availAttr = input.getAttribute('data-available');
        var hasAvail = availAttr !== '' && availAttr != null;
        var avail = num(availAttr);
        var minStock = num(input.getAttribute('data-min-stock'));
        var hint = tr.querySelector('[data-hint]');

        // Перевищення наявного залишку.
        var over = hasAvail && qty > avail;
        // Низький залишок: резерв опускає доступне нижче мінімуму (не over).
        var low = !over && hasAvail && minStock > 0 && qty > 0 && (avail - qty) < minStock;
        input.classList.toggle('is-over', !!over);
        input.classList.toggle('is-low', !!low);
        if (hint) {
          hint.textContent = over ? 'перевищує наявне'
            : (low ? 'залишок нижче мінімуму' : '');
        }

        // Diff у режимі редагування: порівняння з поточним резервом.
        if (mode === 'edit') {
          var reservedAttr = input.getAttribute('data-reserved');
          var original = reservedAttr === '' || reservedAttr == null ? 0 : num(reservedAttr);
          if (qty !== original) changed++;
        }
      });
      if (countEl) countEl.textContent = String(count);
      if (costEl) costEl.textContent = cost.toFixed(2);
      if (usedEl) usedEl.textContent = String(totalUsed);
      if (returnsEl) returnsEl.textContent = String(totalReturns);
      if (withdrawEl) withdrawEl.textContent = String(totalWithdraw);
      if (changesEl) {
        changesEl.textContent = changed ? ('Змінено позицій: ' + changed) : 'Змін немає';
      }
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
