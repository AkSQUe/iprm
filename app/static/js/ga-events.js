/* ga-events.js -- відправка ключових GA4-подій з форм.
 *
 * Форма позначається атрибутом data-ga-event="<назва події>"
 * (рекомендовані назви GA4: sign_up, generate_lead, begin_checkout).
 * Подія шлеться на submit ПІСЛЯ проходження нативної HTML5-валідації
 * (невалідний submit подію не генерує). gtag використовує sendBeacon,
 * тож перехід на нову сторінку відправку не обриває.
 *
 * Якщо GA вимкнено (gtag відсутній) -- модуль нічого не робить. */
(function () {
  'use strict';

  function send(name, params) {
    if (typeof window.gtag === 'function') {
      window.gtag('event', name, params || {});
    }
  }

  document.querySelectorAll('form[data-ga-event]').forEach(function (form) {
    form.addEventListener('submit', function () {
      send(form.getAttribute('data-ga-event'), {
        form_action: form.getAttribute('action') || window.location.pathname,
      });
    });
  });
})();
