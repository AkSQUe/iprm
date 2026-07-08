/* roi-calc.js -- ROI-калькулятор окупності курсу (сторінка курсу).
 *
 * Контейнер [data-roi-calc] несе data-roi-price (мінімальна вартість
 * курсу, грн). Інпути: [data-roi-check] (середній чек процедури) і
 * [data-roi-count] (процедур на місяць). Виводи: [data-roi-income]
 * (дохід/міс) і [data-roi-payback] (скільки процедур і ~тижнів до
 * окупності). Рахуємо наживо на кожен input. */
(function () {
  'use strict';

  var root = document.querySelector('[data-roi-calc]');
  if (!root) return;

  var price = parseInt(root.getAttribute('data-roi-price'), 10) || 0;
  var checkInput = root.querySelector('[data-roi-check]');
  var countInput = root.querySelector('[data-roi-count]');
  var incomeEl = root.querySelector('[data-roi-income]');
  var paybackEl = root.querySelector('[data-roi-payback]');
  if (!checkInput || !countInput || !incomeEl || !paybackEl || price <= 0) return;

  var WEEKS_PER_MONTH = 4.345;

  function fmt(n) {
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  }

  function pluralUk(n, one, few, many) {
    var m10 = n % 10, m100 = n % 100;
    if (m100 >= 11 && m100 <= 14) return many;
    if (m10 === 1) return one;
    if (m10 >= 2 && m10 <= 4) return few;
    return many;
  }

  function recalc() {
    var check = Math.max(0, parseFloat(checkInput.value) || 0);
    var count = Math.max(0, parseFloat(countInput.value) || 0);

    if (check <= 0) {
      incomeEl.textContent = '—';
      paybackEl.textContent = '—';
      return;
    }

    var income = check * count;
    incomeEl.textContent = count > 0 ? fmt(income) + ' ₴' : '—';

    var procedures = Math.ceil(price / check);
    var text = procedures + ' ' + pluralUk(procedures, 'процедура', 'процедури', 'процедур');
    if (count > 0) {
      var weeks = Math.ceil((procedures / count) * WEEKS_PER_MONTH);
      text += ' (≈ ' + weeks + ' ' + pluralUk(weeks, 'тиждень', 'тижні', 'тижнів') + ')';
    }
    paybackEl.textContent = text;
  }

  checkInput.addEventListener('input', recalc);
  countInput.addEventListener('input', recalc);
  recalc();
})();
