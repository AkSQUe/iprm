/* recaptcha-v3.js -- інтеграція Google reCAPTCHA v3 у форми.

   Розмітка:
     <form data-recaptcha-action="login" ...>...</form>

   Логіка:
   1. Перший submit: preventDefault + stopImmediatePropagation,
      grecaptcha.execute(siteKey, {action}) → токен → пишемо у hidden input
      name="g-recaptcha-response", ставимо прапорець __recaptchaReady=true,
      form.requestSubmit() для повторного сабміту.
   2. Другий submit: прапорець підказує що токен вже є -- пропускаємо.
      Звідси form-validate.js (capture, ПЕРШИЙ) знову валідує (вже passed),
      form-single-submit.js (bubble) блокує подвійний клік.

   Координація з form-validate.js: ми -- capture, але реєструємось ПІСЛЯ
   form-validate.js (через defer + порядок у base.html), тож form-validate
   спрацьовує перший. Якщо невалідно -- stopImmediatePropagation у нього
   зупиняє нас. Якщо валідно -- спрацьовуємо ми.

   Site key читаємо з <meta name="recaptcha-site-key" content="...">,
   який рендерить partials/_recaptcha.html (тільки при is_active).

   Single Responsibility: лише видобуток і вшивання v3-токена. */
(function () {
  'use strict';

  var meta = document.querySelector('meta[name="recaptcha-site-key"]');
  var SITE_KEY = meta ? meta.getAttribute('content') : '';

  if (!SITE_KEY) return; // інтеграція не активна -- noop

  function ensureToken(form, action) {
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

  function bindForm(form) {
    if (form.__recaptchaBound) return;
    form.__recaptchaBound = true;
    var action = form.getAttribute('data-recaptcha-action') || 'submit';

    form.addEventListener('submit', function (e) {
      if (form.__recaptchaReady) return; // токен вже отримано -- пропускаємо
      e.preventDefault();
      e.stopImmediatePropagation();

      ensureToken(form, action).then(
        function (token) {
          writeToken(form, token);
          form.__recaptchaReady = true;
          // Скидаємо guard form-single-submit (якщо встиг застосуватись)
          if (form.dataset.submitting === 'true') {
            form.dataset.submitting = 'false';
          }
          if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
          } else {
            form.submit();
          }
        },
        function (err) {
          // Якщо токен не вдалося отримати -- fail-open: відправляємо без
          // токена (сервер вирішить fail-open чи fail-closed). Логуємо.
          if (window.console) console.warn('recaptcha v3: token error', err);
          form.__recaptchaReady = true;
          if (form.dataset.submitting === 'true') {
            form.dataset.submitting = 'false';
          }
          if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
          } else {
            form.submit();
          }
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
