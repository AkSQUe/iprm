/* liqpay-checkout.js -- оплата у вікні LiqPay поверх нашої сторінки.

   Навіщо: у звичайному флоу ми POST-имо форму на liqpay.ua, і після оплати
   людина лишається на ЇХНІЙ сторінці-квитанції, звідки повертається на сайт
   кнопкою (або за таймером, тривалість якого не наша ручка). Віджет прибирає
   цей крок цілком: покупець нікуди не йде, а після колбека ми ведемо його на
   сторінку результату самі.

   Progressive enhancement: форма лишається звичайним POST-ом. Якщо скрипт
   LiqPay не завантажився (блокувальник, CSP, мережа) або JS вимкнено --
   ми НЕ перехоплюємо сабміт, і оплата йде старим шляхом. Зламати оплату
   заради зручності повернення не можна.

   Статус із колбека -- лише привід перейти на сторінку результату, а не
   доказ оплати. Правду про гроші приносить серверний callback LiqPay і
   перевірка статусу на самій сторінці; браузеру тут не вірять. */
(function () {
  'use strict';

  var forms = document.querySelectorAll('form[data-liqpay-form]');
  if (!forms.length) return;

  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  var LIB_URL = 'https://static.liqpay.ua/libjs/checkout.js';

  // 'loading' -> 'ready' | 'failed'. Поки не 'ready', сабміт іде як звичайно:
  // краще старий шлях з кнопкою, ніж мертва кнопка.
  var libState = 'loading';
  var widgetOpen = false;
  // Перехід уже розпочато -- більше нічого зі сторінкою не робимо.
  var navigating = false;
  var pendingButton = null;

  var script = document.createElement('script');
  script.src = LIB_URL;
  script.async = true;
  script.onload = function () {
    libState = window.LiqPayCheckout ? 'ready' : 'failed';
  };
  script.onerror = function () {
    libState = 'failed';
  };
  document.head.appendChild(script);

  /* Кнопка мусить показати, що клік почуто: data-single-submit ми свідомо
     обходимо (див. нижче), тож стандартний стан "Надсилаємо…" не вмикається,
     і поки вікно піднімається, сторінка виглядає застиглою. */
  function markOpening(form) {
    var button = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!button) return;
    pendingButton = { node: button, label: button.textContent };
    button.disabled = true;
    if (button.textContent) button.textContent = t('Відкриваємо оплату…');
  }

  function restoreButton() {
    if (!pendingButton) return;
    pendingButton.node.disabled = false;
    if (pendingButton.label) pendingButton.node.textContent = pendingButton.label;
    pendingButton = null;
  }

  /* Капітальна фаза (третій аргумент true) -- не примха.
     form-single-submit.js слухає submit на document і блокує кнопку, але
     має захисник `if (e.defaultPrevented) return`. Наш обробник мусить
     відпрацювати РАНІШЕ: інакше кнопку вимкнуть, а коли покупець закриє
     вікно LiqPay, форма лишиться мертвою до перезавантаження сторінки.
     Захист від подвійного відкриття беремо на себе (widgetOpen). */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form || !form.matches || !form.matches('form[data-liqpay-form]')) return;
    if (libState !== 'ready' || !window.LiqPayCheckout) return;

    e.preventDefault();
    if (widgetOpen) return;

    var resultUrl = form.getAttribute('data-liqpay-result-url');
    var data = form.getAttribute('data-liqpay-data');
    var signature = form.getAttribute('data-liqpay-signature');
    if (!data || !signature || !resultUrl) return;

    widgetOpen = true;
    markOpening(form);

    try {
      window.LiqPayCheckout.init({
        data: data,
        signature: signature,
        mode: 'popup'
      }).on('liqpay.callback', function (payload) {
        /* Ведемо на сторінку результату за будь-якого статусу, КРІМ явної
           відмови: там уже є опитування справжнього статусу, і воно скаже
           правду навіть про невідомий нам код. Невдалу оплату лишаємо на
           місці -- людина має змогу спробувати ще раз, не блукаючи. */
        var status = payload && payload.status;
        if (status === 'failure' || status === 'error') {
          widgetOpen = false;
          restoreButton();
          return;
        }
        navigating = true;
        window.location.assign(resultUrl);
      }).on('liqpay.close', function () {
        widgetOpen = false;
        /* Перехід уже розпочато -- reload скасував би його й лишив людину
           на сторінці оплати замість сторінки результату. */
        if (navigating) return;
        /* Інакше перезавантажуємо: покупець міг оплатити й закрити вікно
           швидше за колбек. Тоді сторінка лишалась би зі станом "Оплатити"
           за вже оплаченим замовленням -- і людина заплатила б удруге.
           Сервер знає правду: оплачено -> покаже успіх, ні -> ту саму форму. */
        window.location.reload();
      });
    } catch (err) {
      /* Віджет не піднявся -- повертаємось до звичайного POST. form.submit()
         не проходить через обробники, тож рекурсії тут немає. */
      widgetOpen = false;
      restoreButton();
      form.submit();
    }
  }, true);
})();
