/* posthog-events.js -- дублює ключові конверсійні події з форм у PostHog.

   Читає ТІ САМІ атрибути, що й ga-events.js (data-ga-event,
   data-ga-event-load, data-ga-param-*), а не власні data-ph-event. Причина
   проста: розмітка вже стоїть у шаблонах, і другий паралельний набір
   атрибутів означав би, що рано чи пізно форму позначать для GA і забудуть
   для PostHog -- розходження, помітне лише через тиждень у звітах.

   Назви подій лишаються GA4-івські (sign_up, generate_lead, begin_checkout).
   PostHog не має власного словника обов'язкових назв, тож тримати два
   різні імені однієї конверсії було б лише джерелом плутанини між звітами.

   Якщо PostHog вимкнено, window.posthog відсутній -- модуль нічого не
   робить. Якщо SDK ще не приїхав, виклики лягають у стаб-чергу з
   posthog.js і програються, щойно він завантажиться. */
(function () {
  'use strict';

  function send(name, params) {
    if (window.posthog && typeof window.posthog.capture === 'function') {
      window.posthog.capture(name, params || {});
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
