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
  var forms = document.querySelectorAll('form[data-liqpay-form]');
  if (!forms.length) return;

  var LIB_URL = 'https://static.liqpay.ua/libjs/checkout.js';

  // 'loading' -> 'ready' | 'failed'. Поки не 'ready', сабміт іде як звичайно:
  // краще старий шлях з кнопкою, ніж мертва кнопка.
  var libState = 'loading';
  var widgetOpen = false;

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
        return;
      }
      window.location.assign(resultUrl);
    }).on('liqpay.close', function () {
      widgetOpen = false;
    });
  }, true);
})();
