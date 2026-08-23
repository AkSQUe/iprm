/* meta-events.js -- відправка подій конверсій у Meta Pixel.

   Точки трекінгу вже розставлені в шаблонах атрибутами data-ga-event /
   data-ga-event-load (див. analytics-events.js). Другий, паралельний набір
   meta-атрибутів на тих самих формах означав би два списки, які неминуче
   роз'їдуться, тож тут ми читаємо ті самі атрибути і мапимо назву GA4-події
   на стандартну назву Meta (GA_TO_META).

   Для точок, потрібних лише Meta, є власні атрибути data-meta-event і
   data-meta-event-load -- вони мають пріоритет над ga-назвою на тому самому
   елементі. Параметри події -- через data-meta-param-* (data-meta-param-value
   -> {value: ...}), за зразком data-ga-param-*.

   Якщо Pixel вимкнено (fbq відсутній) -- модуль нічого не робить. */
(function () {
  'use strict';

  // GA4-подія -> стандартна подія Meta.
  var GA_TO_META = {
    sign_up: 'CompleteRegistration',
    generate_lead: 'Lead',
    begin_checkout: 'InitiateCheckout',
    referral_signup: 'Lead',
    purchase: 'Purchase'
  };

  /* Стандартні події Meta йдуть через track(), решта -- через trackCustom().
     Якщо надіслати нестандартну назву через track(), Events Manager приймає
     її, але не рахує як конверсію -- мовчазна втрата даних. */
  var STANDARD_EVENTS = [
    'AddPaymentInfo', 'AddToCart', 'AddToWishlist', 'CompleteRegistration',
    'Contact', 'CustomizeProduct', 'Donate', 'FindLocation', 'InitiateCheckout',
    'Lead', 'PageView', 'Purchase', 'Schedule', 'Search', 'StartTrial',
    'SubmitApplication', 'Subscribe', 'ViewContent'
  ];

  /* Числові параметри Meta мусять бути числами, а не рядками: value з
     data-атрибута приходить рядком, і Purchase з value="4500" не
     підсумовується у звітах. */
  var NUMERIC_PARAMS = ['value'];

  /* content_ids Meta очікує масивом. Рядок вона приймає, але тоді каталожні
     звіти (яким товаром цікавились) лишаються порожні -- помилка тиха. */
  var ARRAY_PARAMS = ['content_ids'];

  /* eventID -- дедуплікація на боці Meta (вікно 48 годин).
     Потрібен там, де подія прив'язана до завантаження сторінки, яку можна
     відкрити повторно: сторінку успішної оплати користувач бачить після
     редиректу LiqPay, а тоді ще й оновлює або повертається "назад". Без
     стабільного ID кожен такий перегляд рахувався б окремою покупкою --
     завищений ROAS і зіпсоване навчання алгоритму. */
  function send(name, params, eventId) {
    if (typeof window.fbq !== 'function') return;
    var method = STANDARD_EVENTS.indexOf(name) !== -1 ? 'track' : 'trackCustom';
    if (eventId) {
      window.fbq(method, name, params || {}, { eventID: eventId });
    } else {
      window.fbq(method, name, params || {});
    }
  }

  /* Назва події для елемента: власний meta-атрибут або мапінг з ga-назви.
     Порожня строка -- елемент пропускаємо (ga-подія без відповідника). */
  function eventName(el, metaAttr, gaAttr) {
    var own = el.getAttribute(metaAttr);
    if (own) return own;
    var ga = el.getAttribute(gaAttr);
    return (ga && GA_TO_META[ga]) || '';
  }

  /* dataset нормалізує data-meta-param-content-name у metaParamContentName,
     а параметри Meta -- snake_case (content_name). Без цієї конвертації
     Events Manager мовчки ігнорує параметр як невідомий. */
  function toSnakeCase(s) {
    return s.replace(/[A-Z]/g, function (c) { return '_' + c.toLowerCase(); });
  }

  function collectParams(el) {
    var params = {};
    Object.keys(el.dataset).forEach(function (k) {
      // data-meta-param-content-name -> dataset.metaParamContentName -> content_name
      if (k.indexOf('metaParam') === 0 && k.length > 9) {
        var key = toSnakeCase(k.charAt(9).toLowerCase() + k.slice(10));
        var raw = el.dataset[k];
        if (NUMERIC_PARAMS.indexOf(key) !== -1) {
          var num = parseFloat(raw);
          params[key] = isNaN(num) ? raw : num;
        } else if (ARRAY_PARAMS.indexOf(key) !== -1) {
          params[key] = [raw];
        } else {
          params[key] = raw;
        }
      }
    });
    return params;
  }

  function bind() {
    // Події на сабміті форми. Спрацьовує після нативної HTML5-валідації, тож
    // невалідний сабміт конверсію не генерує.
    document.querySelectorAll('form[data-ga-event], form[data-meta-event]')
      .forEach(function (form) {
        var name = eventName(form, 'data-meta-event', 'data-ga-event');
        if (!name) return;
        form.addEventListener('submit', function () {
          send(name, collectParams(form));
        });
      });

    // Події на завантаженні сторінки (підтвердження реєстрації, успішна оплата).
    document.querySelectorAll('[data-ga-event-load], [data-meta-event-load]')
      .forEach(function (el) {
        var name = eventName(el, 'data-meta-event-load', 'data-ga-event-load');
        if (!name) return;
        send(name, collectParams(el), el.getAttribute('data-meta-event-id'));
      });
  }

  bind();
})();
