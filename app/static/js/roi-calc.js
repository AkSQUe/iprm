/* roi-calc.js -- ROI-калькулятор окупності курсу (сторінка курсу).
 *
 * Контейнер [data-roi-calc] несе data-roi-price (мінімальна вартість
 * курсу, грн). Інпути: [data-roi-check] (середній чек процедури) і
 * [data-roi-count] (процедур на місяць). Виводи: [data-roi-income]
 * (дохід/міс) і [data-roi-payback] (скільки процедур і ~тижнів до
 * окупності). Рахуємо наживо на кожен input. */
(function () {
  'use strict';

  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  var root = document.querySelector('[data-roi-calc]');
  if (!root) return;

  // Опційний селектор курсу (Головна): ціна береться з обраного <option
  // data-price>. На сторінці курсу селектора немає -> ціна з data-roi-price.
  var courseSel = root.querySelector('[data-roi-course]');
  var priceOut = root.querySelector('[data-roi-price-out]');
  var checkInput = root.querySelector('[data-roi-check]');
  var countInput = root.querySelector('[data-roi-count]');
  var incomeEl = root.querySelector('[data-roi-income]');
  var paybackEl = root.querySelector('[data-roi-payback]');
  // Строк окупності окремим елементом: у двопанельному варіанті головне
  // число ("4 процедури") стоїть саме, а "≈ 2 тижнів" живе в реченні під
  // ним. Старий однорядковий варіант його не мав -- лишаємо опційним.
  var timeEl = root.querySelector('[data-roi-time]');
  if (!checkInput || !countInput || !incomeEl || !paybackEl) return;

  // Дзеркала значень поруч із підписом. Потрібні лише повзунковому варіанту
  // (range не показує число сам); у числових полях значення видно в самому
  // полі, тож там цих елементів у розмітці немає.
  var checkOut = root.querySelector('[data-roi-check-out]');
  var countOut = root.querySelector('[data-roi-count-out]');

  function currentPrice() {
    if (courseSel && courseSel.options.length) {
      var opt = courseSel.options[courseSel.selectedIndex];
      return opt ? (parseInt(opt.getAttribute('data-price'), 10) || 0) : 0;
    }
    return parseInt(root.getAttribute('data-roi-price'), 10) || 0;
  }

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
    var price = currentPrice();
    if (priceOut) priceOut.textContent = price > 0 ? fmt(price) + ' ₴' : '—';

    var check = Math.max(0, parseFloat(checkInput.value) || 0);
    var count = Math.max(0, parseFloat(countInput.value) || 0);

    if (checkOut) checkOut.textContent = fmt(check) + ' ₴';
    if (countOut) countOut.textContent = String(count);

    if (check <= 0 || price <= 0) {
      incomeEl.textContent = '—';
      paybackEl.textContent = '—';
      if (timeEl) timeEl.textContent = '—';
      return;
    }

    var income = check * count;
    incomeEl.textContent = count > 0 ? fmt(income) + ' ₴' : '—';

    var procedures = Math.ceil(price / check);
    var proceduresText = procedures + ' '
      + pluralUk(procedures, t('процедура'), t('процедури'), t('процедур'));

    var weeksText = '';
    if (count > 0) {
      var weeks = Math.ceil((procedures / count) * WEEKS_PER_MONTH);
      weeksText = weeks + ' ' + pluralUk(weeks, t('тиждень'), t('тижні'), t('тижнів'));
    }

    if (timeEl) {
      // Двопанельний варіант: число окремо, строк -- у реченні під ним.
      paybackEl.textContent = proceduresText;
      timeEl.textContent = weeksText || '—';
    } else {
      // Однорядковий варіант (Головна): усе в одному рядку, як було.
      paybackEl.textContent = proceduresText
        + (weeksText ? ' (≈ ' + weeksText + ')' : '');
    }
  }

  checkInput.addEventListener('input', recalc);
  countInput.addEventListener('input', recalc);
  if (courseSel) courseSel.addEventListener('change', recalc);
  recalc();
})();
