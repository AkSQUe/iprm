/* recaptcha-v3.js -- інтеграція Google reCAPTCHA v3 у форми.

   Розмітка:
     <form data-recaptcha-action="login" ...>...</form>

   Завантаження api.js (~374 KB) -- ліниве. Розмітка дає лише
   <meta name="recaptcha-site-key"> (partials/_recaptcha.html), а сам скрипт
   вставляємо тут:
     * прогрів -- за першою взаємодією з формою (focusin / pointerdown), коли
       до сабміту лишаються секунди заповнення;
     * гарантія -- ensureToken() у будь-якому разі чекає loadApi(), тож сабміт
       без прогріву (автозаповнення, форма з самої кнопки) теж отримає токен.
   Це прибирає ~500 мс TBT з першого завантаження сторінок із формами.

   Логіка сабміту:
   1. Перший submit: preventDefault + stopImmediatePropagation,
      loadApi() -> grecaptcha.execute(siteKey, {action}) -> токен -> пишемо у
      hidden input name="g-recaptcha-response", ставимо прапорець
      __recaptchaReady=true, form.requestSubmit() для повторного сабміту.
   2. Другий submit: прапорець підказує що токен вже є -- пропускаємо.
      Звідси form-validate.js (capture, ПЕРШИЙ) знову валідує (вже passed),
      form-single-submit.js (bubble) блокує подвійний клік.

   Координація з form-validate.js: ми -- capture, але реєструємось ПІСЛЯ
   form-validate.js (через defer + порядок у base.html), тож form-validate
   спрацьовує перший. Якщо невалідно -- stopImmediatePropagation у нього
   зупиняє нас. Якщо валідно -- спрацьовуємо ми.

   Single Responsibility: лише завантаження api.js, видобуток і вшивання
   v3-токена. */
(function () {
  'use strict';

  var meta = document.querySelector('meta[name="recaptcha-site-key"]');
  var SITE_KEY = meta ? meta.getAttribute('content') : '';

  if (!SITE_KEY) return; // інтеграція не активна -- noop

  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  var LOAD_TIMEOUT_MS = 8000;
  var apiPromise = null;

  /* Вставити api.js один раз. Повертає Promise, що резолвиться на onload.
     На помилці/таймауті -- reject, викликач іде шляхом fail-open. */
  function loadApi() {
    if (apiPromise) return apiPromise;
    apiPromise = new Promise(function (resolve, reject) {
      var script = document.createElement('script');
      script.src = 'https://www.google.com/recaptcha/api.js?render='
        + encodeURIComponent(SITE_KEY);
      script.async = true;
      script.onload = function () { resolve(); };
      script.onerror = function () { reject(new Error('recaptcha api.js load failed')); };
      window.setTimeout(function () {
        reject(new Error('recaptcha api.js load timeout'));
      }, LOAD_TIMEOUT_MS);
      document.head.appendChild(script);
    });
    return apiPromise;
  }

  function ensureToken(form, action) {
    return loadApi().then(function () {
      return new Promise(function (resolve, reject) {
        if (typeof grecaptcha === 'undefined' || !grecaptcha.ready) {
          reject(new Error('grecaptcha not loaded'));
          return;
        }
        grecaptcha.ready(function () {
          try {
            grecaptcha.execute(SITE_KEY, { action: action }).then(resolve, reject);
          } catch (e) {
            reject(e);
          }
        });
      });
    });
  }

  function writeToken(form, token) {
    var input = form.querySelector('input[name="g-recaptcha-response"]');
    if (!input) {
      input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'g-recaptcha-response';
      form.appendChild(input);
    }
    input.value = token;
  }

  /* Поки чекаємо api.js, кнопка має показувати роботу: без прогріву це може
     бути кілька секунд на повільному каналі. Механіка та сама, що у
     form-single-submit.js, тож наступний (справжній) сабміт бачить узгоджений
     стан. */
  function markPending(form) {
    if (form.dataset.submitting === 'true') return;
    form.dataset.submitting = 'true';
    form.querySelectorAll('button[type="submit"], input[type="submit"]')
      .forEach(function (btn) {
        btn.disabled = true;
        if (btn.dataset.defaultLabel === undefined && btn.textContent) {
          btn.dataset.defaultLabel = btn.textContent;
          btn.textContent = t('Надсилаємо…');
        }
      });
  }

  function resubmit(form) {
    form.__recaptchaReady = true;
    // Скидаємо guard form-single-submit (якщо встиг застосуватись)
    if (form.dataset.submitting === 'true') {
      form.dataset.submitting = 'false';
    }
    form.querySelectorAll('button[type="submit"], input[type="submit"]')
      .forEach(function (btn) { btn.disabled = false; });
    if (typeof form.requestSubmit === 'function') {
      form.requestSubmit();
    } else {
      form.submit();
    }
  }

  function bindForm(form) {
    if (form.__recaptchaBound) return;
    form.__recaptchaBound = true;
    var action = form.getAttribute('data-recaptcha-action') || 'submit';

    // Прогрів: перша взаємодія з формою -- сигнал, що сабміт близько.
    var warmUp = function () { loadApi().catch(function () {}); };
    form.addEventListener('focusin', warmUp, { once: true });
    form.addEventListener('pointerdown', warmUp, { once: true });

    form.addEventListener('submit', function (e) {
      if (form.__recaptchaReady) return; // токен вже отримано -- пропускаємо
      e.preventDefault();
      e.stopImmediatePropagation();
      markPending(form);

      ensureToken(form, action).then(
        function (token) {
          writeToken(form, token);
          resubmit(form);
        },
        function (err) {
          // Якщо токен не вдалося отримати -- fail-open: відправляємо без
          // токена (сервер вирішить fail-open чи fail-closed). Логуємо.
          if (window.console) console.warn('recaptcha v3: token error', err);
          resubmit(form);
        }
      );
    }, true);
  }

  function init() {
    document.querySelectorAll('form[data-recaptcha-action]').forEach(bindForm);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
