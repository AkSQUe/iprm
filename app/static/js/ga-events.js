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

  // Події на завантаженні сторінки: елемент [data-ga-event-load="<name>"]
  // (напр. реферальна конверсія на сторінці підтвердження). Доп. параметри --
  // через data-ga-param-* (data-ga-param-value -> {value: ...}).
  document.querySelectorAll('[data-ga-event-load]').forEach(function (el) {
    var params = {};
    Object.keys(el.dataset).forEach(function (k) {
      if (k.indexOf('gaParam') === 0 && k.length > 7) {
        var key = k.charAt(7).toLowerCase() + k.slice(8);
        params[key] = el.dataset[k];
      }
    });
    send(el.getAttribute('data-ga-event-load'), params);
  });
})();
