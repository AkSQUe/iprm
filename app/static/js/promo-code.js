/* promo-code.js -- перевірка промокоду на формі реєстрації без сабміту.
 *
 * Кнопка [data-promo-apply] шле код на data-url і показує результат:
 * повідомлення під полем, рядок знижки у зведенні і перерахована сума в
 * усіх [data-tariff-price] (шапка, кнопка, липка панель).
 *
 * Progressive enhancement: без JS код просто їде разом із формою і той
 * самий promo_service перевіряє його на сабміті. Тому тут НЕ блокуємо
 * відправку і не робимо поле обов'язковим -- скрипт лише прибирає
 * непевність "чи спрацює мій код" до оплати.
 *
 * Зміна тарифу скидає застосований код: відсоток від іншої ціни -- інша
 * сума, а показувати стару було б брехнею. Перевіряємо заново самі, щоб
 * людині не довелось тиснути кнопку вдруге.
 */
(function () {
  'use strict';

  var btn = document.querySelector('[data-promo-apply]');
  if (!btn) return;

  var input = document.getElementById('promo_code');
  var status = document.querySelector('[data-promo-status]');
  var summary = document.querySelector('[data-promo-summary]');
  var summaryValue = document.querySelector('[data-promo-summary-value]');
  var priceTargets = document.querySelectorAll('[data-tariff-price]');
  var form = document.getElementById('reg-form');
  var url = btn.getAttribute('data-url') || '';

  // Ціна без знижки на момент завантаження -- база для скидання.
  var appliedCode = null;

  function csrfToken() {
    var field = form && form.querySelector('input[name="csrf_token"]');
    return field ? field.value : '';
  }

  function selectedTariffId() {
    var radio = document.querySelector('[data-tariff-radio]:checked');
    return radio ? radio.value : '';
  }

  function basePrice() {
    // Тарифна вилка: базу задає обране радіо. Подія без тарифів радіо не
    // має -- там базу несе сам блок промокоду, інакше зняття коду лишало б
    // на екрані зменшену ціну, якої сервер не виставить.
    var radio = document.querySelector('[data-tariff-radio]:checked');
    if (radio) return radio.getAttribute('data-price');
    var row = document.querySelector('[data-base-price]');
    return row ? row.getAttribute('data-base-price') : null;
  }

  function setStatus(text, ok) {
    if (!status) return;
    status.textContent = text || '';
    status.hidden = !text;
    status.classList.toggle('reg-promo__status--ok', !!ok);
    status.classList.toggle('reg-promo__status--error', !!text && !ok);
  }

  function setPrice(value) {
    if (value === null || value === undefined) return;
    priceTargets.forEach(function (el) {
      el.textContent = value + ' ₴';
    });
  }

  function showDiscount(discount) {
    if (!summary) return;
    if (discount > 0) {
      if (summaryValue) summaryValue.textContent = '−' + discount + ' ₴';
      summary.hidden = false;
    } else {
      summary.hidden = true;
    }
  }

  function reset(message) {
    appliedCode = null;
    showDiscount(0);
    var base = basePrice();
    if (base !== null) setPrice(base);
    setStatus(message || '', false);
  }

  function check(silent) {
    var code = (input && input.value ? input.value : '').trim();
    if (!code) {
      reset('');
      return;
    }
    if (!url) return;

    btn.disabled = true;
    var body = new URLSearchParams();
    body.set('code', code);
    body.set('tariff_id', selectedTariffId());

    fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: body.toString(),
      credentials: 'same-origin'
    })
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        if (data && data.ok) {
          appliedCode = code;
          showDiscount(data.discount);
          setPrice(data.final);
          setStatus(data.message, true);
        } else {
          reset((data && data.message) || '');
        }
      })
      .catch(function () {
        // Мережа впала -- мовчимо у фоновій перевірці, бо код усе одно
        // поїде на сервер разом із формою.
        if (!silent) setStatus('', false);
      })
      .finally(function () {
        btn.disabled = false;
      });
  }

  btn.addEventListener('click', function () { check(false); });

  if (input) {
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        // Enter у полі промокоду не має відправляти всю форму.
        e.preventDefault();
        check(false);
      }
    });
    input.addEventListener('input', function () {
      if (appliedCode && input.value.trim() !== appliedCode) reset('');
    });
  }

  document.querySelectorAll('[data-tariff-radio]').forEach(function (radio) {
    radio.addEventListener('change', function () {
      if (radio.checked && appliedCode) check(true);
    });
  });
})();
