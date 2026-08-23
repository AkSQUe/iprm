/* analytics-events.js -- ключові конверсійні події з форм у GA4 і PostHog.

   Раніше це були два файли -- ga-events.js і posthog-events.js -- що
   збігалися дослівно, крім одного рядка з назвою приймача. Дубль тримався
   рівно доти, доки хтось не виправив би парсер параметрів в одному місці й
   не забув у другому; розходження такого роду помітне лише через тиждень у
   звітах, коли числа перестають сходитись.

   Точки трекінгу розставлені в шаблонах атрибутами data-ga-event /
   data-ga-event-load; параметри -- через data-ga-param-*
   (data-ga-param-value -> {value: ...}). Префікс лишається "ga-" попри те,
   що приймачів тепер два: перейменування зачепило б десятки шаблонів, а
   виграш був би косметичний.

   Meta Pixel має власний meta-events.js і сюди НЕ входить: там інша
   семантика (мапінг на стандартні назви Meta, числові й масивні параметри,
   eventID для дедуплікації), тож звести їх в одне означало б не прибрати
   дубль, а злити дві різні логіки.

   Кожен приймач перевіряється окремо: файл підключається, коли активний
   ХОЧА Б один, і мовчки пропускає відсутнього. Виклики posthog до приходу
   SDK лягають у стаб-чергу з posthog.js і програються пізніше. */
(function () {
  'use strict';

  function send(name, params) {
    var payload = params || {};
    if (typeof window.gtag === 'function') {
      window.gtag('event', name, payload);
    }
    if (window.posthog && typeof window.posthog.capture === 'function') {
      window.posthog.capture(name, payload);
    }
  }

  /* dataset нормалізує data-ga-param-value у gaParamValue -- зрізаємо
     префікс і повертаємо першу літеру в нижній регістр. */
  function collectParams(el) {
    var params = {};
    Object.keys(el.dataset).forEach(function (k) {
      if (k.indexOf('gaParam') === 0 && k.length > 7) {
        var key = k.charAt(7).toLowerCase() + k.slice(8);
        params[key] = el.dataset[k];
      }
    });
    return params;
  }

  // Події на сабміті форми. Спрацьовує після нативної HTML5-валідації, тож
  // невалідний сабміт конверсію не генерує.
  document.querySelectorAll('form[data-ga-event]').forEach(function (form) {
    form.addEventListener('submit', function () {
      send(form.getAttribute('data-ga-event'), {
        form_action: form.getAttribute('action') || window.location.pathname,
      });
    });
  });

  // Події на завантаженні сторінки: [data-ga-event-load="<name>"]
  // (напр. реферальна конверсія на сторінці підтвердження).
  document.querySelectorAll('[data-ga-event-load]').forEach(function (el) {
    send(el.getAttribute('data-ga-event-load'), collectParams(el));
  });
})();
