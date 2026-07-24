/* registration-pay.js — UX-фідбек при завантаженні рахунка.

   Кнопки/посилання [data-invoice-download] дають toast-підказку, бо рахунок
   формується на сервері (WeasyPrint) і віддача може зайняти секунду.
   Підключається на сторінках, де є посилання на рахунок: confirmation,
   complete_pay, особистий кабінет.

   Vanilla JS, без залежностей. Progressive enhancement: без JS посилання
   працює як звичайне завантаження. */
(function () {
  'use strict';

  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  var invoiceLinks = document.querySelectorAll('[data-invoice-download]');
  invoiceLinks.forEach(function (a) {
    a.addEventListener('click', function () {
      if (typeof window.iprmToast === 'function') {
        window.iprmToast(
          t('Формуємо рахунок (PDF) — завантаження почнеться за мить.'),
          'info',
          { title: t('Рахунок') }
        );
      }
    });
  });
})();
