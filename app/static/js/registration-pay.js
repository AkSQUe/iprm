/* registration-pay.js — UX-підсилення вибору способу оплати.

   1) Форма реєстрації: показує підказку, коли обрано «Оплата за рахунком».
   2) Кнопки завантаження рахунка ([data-invoice-download]) дають toast-фідбек
      (рахунок формується на сервері WeasyPrint, віддача може зайняти секунду).

   Vanilla JS, без залежностей. Progressive enhancement: без JS форма й
   посилання працюють як є. */
(function () {
  'use strict';

  // ----- 1) Підказка для способу «Оплата за рахунком» -----
  var hint = document.querySelector('[data-pay-invoice-hint]');
  var radios = document.querySelectorAll('input[name="payment_method"]');

  function syncHint() {
    if (!hint) return;
    var checked = document.querySelector('input[name="payment_method"]:checked');
    hint.hidden = !(checked && checked.value === 'invoice');
  }

  if (hint && radios.length) {
    radios.forEach(function (r) { r.addEventListener('change', syncHint); });
    syncHint();
  }

  // ----- 2) Toast при завантаженні рахунка -----
  var invoiceLinks = document.querySelectorAll('[data-invoice-download]');
  invoiceLinks.forEach(function (a) {
    a.addEventListener('click', function () {
      if (typeof window.iprmToast === 'function') {
        window.iprmToast(
          'Формуємо рахунок (PDF) — завантаження почнеться за мить.',
          'info',
          { title: 'Рахунок' }
        );
      }
    });
  });
})();
