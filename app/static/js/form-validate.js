/* form-validate.js — клієнтська валідація форм [data-validate].

   Три моменти перевірки (progressive disclosure, «не сварити наперед»):
     1. blur (focusout) — поле перевіряється, коли користувач його залишає,
        але лише якщо він у ньому щось набирав;
     2. success — валідне поле отримує позитивне підтвердження (зелена рамка,
        галочка, опційна підказка через [data-valid-hint]), а не лише мовчання;
     3. live — поле, яке ВЖЕ помилилось (на submit, на blur або з боку
        сервера), далі перевіряється на кожному вводі: помилка зникає в мить
        виправлення. Нову помилку під час набору не показуємо — щоб не сварити
        за недонабраний email.

   Поведінка при submit невалідної форми:
     - scroll до першого проблемного поля (smooth, по центру)
     - підсвічування + shake-анімація
     - інлайн-підказка під полем
     - focus
     - toast (якщо доступний window.iprmToast з toast.js)

   Підтримка груп radio/checkbox через [data-required-group] + [data-hint].
   Звірка полів: [data-match="#selector"] (+ опційний [data-match-hint]).

   Залежність (опціональна): toast.js для нотифікації «Перевірте форму».
   Single Responsibility: лише валідація. */
(function () {
  'use strict';

  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ
  // (із підстановкою {токенів}, щоб без i18n.js не світились плейсхолдери).
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k, params) {
    if (!params) return k;
    return k.replace(/\{(\w+)\}/g, function (m, name) {
      return Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : m;
    });
  };

  var HINT_DEFAULT = t('Будь ласка, заповніть це поле');
  // Підказки для ПОРОЖНЬОГО обов'язкового поля.
  var HINT_EMPTY = {
    date: t('Оберіть дату'),
    checkbox: t('Необхідно поставити цю позначку'),
  };
  // Підказки для заповненого поля з неправильним ФОРМАТОМ.
  var HINT_FORMAT = {
    email: t('Вкажіть коректну адресу електронної пошти'),
    tel: t('Вкажіть номер у форматі +380XXXXXXXXX'),
  };
  var HINT_OK_DEFAULT = t('Виглядає добре');

  // Дзеркало серверних правил: Email() з WTForms (домен із крапкою) та
  // app/utils.py normalize_phone + UA_PHONE_RE.
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@.]{2,}$/;
  var TEL_NAME_RE = /phone|(^|[_-])tel([_-]|$)/;

  // Поля, які «набирали» (був input/change) і які перейшли в live-режим.
  var touched = new WeakSet();
  var live = new WeakSet();

  function notify(message, type) {
    if (typeof window.iprmToast === 'function') {
      window.iprmToast(message, type);
    }
  }

  function groupOf(el) {
    return el.closest('.form-group, .reg-form-section, .form-consent') || el.parentNode;
  }

  /* Куди класти підказку. Для прапорця -- у його власний .form-checkbox:
     в одному .form-consent їх буває кілька, і спільний контейнер з'їдав би
     підказку сусіда. */
  function hintHost(el) {
    return el.closest('.form-checkbox') || groupOf(el);
  }

  /* --- Визначення «сорту» поля -------------------------------------------
     WTForms рендерить StringField як type="text", тому тип поля вгадуємо ще
     й за name/id/autocomplete -- інакше email і телефон лишились би без
     перевірки формату. */
  function fieldKind(field) {
    var type = (field.getAttribute('type') || field.type || '').toLowerCase();
    if (type === 'email' || type === 'tel' || type === 'date' || type === 'checkbox' || type === 'radio') {
      return type;
    }
    var name = ((field.name || '') + ' ' + (field.id || '') + ' ' + (field.getAttribute('autocomplete') || '')).toLowerCase();
    if (name.indexOf('email') !== -1) return 'email';
    if (TEL_NAME_RE.test(name)) return 'tel';
    return type || 'text';
  }

  function isValidPhone(value) {
    var digits = value.replace(/\D/g, '');
    return (digits.length === 12 && digits.indexOf('380') === 0)   // 380XXXXXXXXX
        || (digits.length === 10 && digits.charAt(0) === '0')      // 0XXXXXXXXX
        || digits.length === 9;                                    // XXXXXXXXX
  }

  /* Повертає текст помилки або null, якщо поле валідне. */
  function fieldError(field) {
    var kind = fieldKind(field);
    var value = (field.value || '').trim();
    var required = field.hasAttribute('required') || field.hasAttribute('data-required');

    if (!value) {
      if (!required) return null;
      return field.getAttribute('data-hint') || HINT_EMPTY[kind] || HINT_DEFAULT;
    }

    if (kind === 'email' && !EMAIL_RE.test(value)) return HINT_FORMAT.email;
    if (kind === 'tel' && !isValidPhone(value)) return HINT_FORMAT.tel;

    var min = parseInt(field.getAttribute('minlength'), 10);
    if (min && value.length < min) return t('Мінімум {n} символів', { n: min });

    var matchSel = field.getAttribute('data-match');
    if (matchSel) {
      var other = document.querySelector(matchSel);
      if (other && other.value !== field.value) {
        return field.getAttribute('data-match-hint') || t('Значення не збігаються');
      }
    }

    if (field.checkValidity && !field.checkValidity()) {
      return HINT_FORMAT[kind] || field.validationMessage || HINT_DEFAULT;
    }
    return null;
  }

  /* --- Візуальні стани поля ---------------------------------------------- */

  function removeHints(group) {
    group.querySelectorAll('.field-hint--js, .field-hint--ok').forEach(function (h) { h.remove(); });
  }

  /* Прибирає й серверну розмітку помилки (.is-invalid + .form-error): щойно
     користувач правит поле, старий текст від сервера стає шумом. */
  function clearServerError(field) {
    if (!field.classList.contains('is-invalid')) return;
    field.classList.remove('is-invalid');
    groupOf(field).querySelectorAll('.form-error').forEach(function (e) { e.remove(); });
  }

  function clearFieldError(field) {
    field.classList.remove('field-invalid');
    var hint = hintHost(field).querySelector('.field-hint--js');
    if (hint) hint.remove();
  }

  function clearFieldState(field) {
    field.classList.remove('field-invalid', 'field-valid');
    field.removeAttribute('aria-invalid');
    removeHints(hintHost(field));
  }

  /* quiet -- показати підказку без shake (для other-полів при submit:
     трясти всю форму одразу -- забагато руху). */
  function showFieldError(field, message, quiet) {
    var anchor = field;
    var group = hintHost(anchor);

    removeHints(group);
    anchor.classList.remove('field-valid');

    var hint = document.createElement('div');
    hint.className = 'field-hint field-hint--js';
    hint.setAttribute('role', 'alert');
    hint.textContent = message;
    group.appendChild(hint);

    anchor.classList.add('field-invalid');
    if (anchor.matches('input, select, textarea')) anchor.setAttribute('aria-invalid', 'true');
    if (quiet) return;
    anchor.addEventListener('animationend', function () {
      anchor.classList.remove('field-shake');
    }, { once: true });
    anchor.classList.add('field-shake');
  }

  /* Позитивне підтвердження: рамка + галочка завжди, текстова підказка --
     лише для полів із [data-valid-hint] (щоб не засипати форму «ОК»). */
  function showFieldOk(field) {
    var group = hintHost(field);
    removeHints(group);
    field.classList.remove('field-invalid');
    field.classList.add('field-valid');
    field.setAttribute('aria-invalid', 'false');

    if (field.hasAttribute('data-valid-hint')) {
      var hint = document.createElement('div');
      hint.className = 'field-hint field-hint--ok';
      hint.setAttribute('aria-live', 'polite');
      hint.textContent = field.getAttribute('data-valid-hint') || HINT_OK_DEFAULT;
      group.appendChild(hint);
    }
  }

  /* Чи має сенс показувати позитивний стан. Порожнє необов'язкове поле --
     не «успіх», а просто порожнє. Прапорці/радіо самі себе підтверджують. */
  function canConfirm(field) {
    var kind = fieldKind(field);
    if (kind === 'checkbox' || kind === 'radio') return false;
    if (field.hasAttribute('data-no-confirm')) return false;
    return !!(field.value || '').trim();
  }

  /* Перерахунок поля в live-режимі (під час набору). Помилку не показуємо --
     лише прибираємо застарілий позитивний стан або підтверджуємо виправлення. */
  function refreshLive(field) {
    if (!fieldError(field)) {
      if (canConfirm(field)) showFieldOk(field);
      else clearFieldState(field);
    } else if (field.classList.contains('field-valid')) {
      clearFieldState(field);
    }
  }

  function firstFocusable(el) {
    if (el.matches('input, select, textarea')) return el;
    return el.querySelector('input, select, textarea') || el;
  }

  function textFields(form) {
    return form.querySelectorAll(
      'input[required], select[required], textarea[required],' +
      'input[data-required], select[data-required], textarea[data-required],' +
      'input[data-match], input[data-valid-hint]'
    );
  }

  function validateForm(form) {
    var invalids = [];
    var seen = new WeakSet();

    // Стандартні поля з [required] / [data-required] / [data-match]
    textFields(form).forEach(function (field) {
      if (field.type === 'radio' || field.type === 'checkbox') return;
      if (seen.has(field)) return;
      seen.add(field);
      clearFieldError(field);
      var msg = fieldError(field);
      if (msg) invalids.push({ el: field, msg: msg });
    });

    // Обов'язкова одиночна checkbox (згода)
    form.querySelectorAll('input[type="checkbox"][required], input[type="checkbox"][data-required]').forEach(function (cb) {
      clearFieldError(cb);
      if (!cb.checked) {
        invalids.push({ el: cb, msg: cb.getAttribute('data-hint') || HINT_EMPTY.checkbox });
      }
    });

    // Групи radio / checkbox
    form.querySelectorAll('[data-required-group]').forEach(function (group) {
      var inputs = group.querySelectorAll('input[type="radio"], input[type="checkbox"]');
      var checked = Array.prototype.some.call(inputs, function (i) { return i.checked; });
      var hintEl = group.querySelector('.field-hint--js');
      if (hintEl) hintEl.remove();
      group.classList.remove('field-invalid');
      if (!checked && inputs.length) {
        invalids.push({
          el: group,
          msg: group.getAttribute('data-hint') || t('Оберіть хоча б один варіант'),
          isGroup: true,
        });
      }
    });

    return invalids;
  }

  function focusInvalid(item) {
    var target = item.el;
    var scrollTarget = target.closest('.form-group, .reg-form-section, .form-consent') || target;
    scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
    showFieldError(item.el, item.msg);
    setTimeout(function () {
      var f = firstFocusable(item.el);
      if (f && f.focus) {
        try { f.focus({ preventScroll: true }); } catch (e) { f.focus(); }
      }
    }, 350);
  }

  function initFormValidation() {
    var forms = document.querySelectorAll('form[data-validate]');
    forms.forEach(function (form) {
      form.setAttribute('novalidate', 'novalidate');

      // Поля, які сервер уже позначив помилковими, одразу в live-режимі:
      // «після помилки -- перевіряти на льоту».
      form.querySelectorAll('.is-invalid').forEach(function (field) {
        if (field.matches('input, select, textarea')) {
          live.add(field);
          touched.add(field);
        }
      });

      // Capture-фаза + stopImmediatePropagation: спрацьовуємо ПЕРШИМИ і при
      // помилці блокуємо bubble-listener form-single-submit.js (інакше
      // кнопка лишилась би disabled назавжди).
      form.addEventListener('submit', function (e) {
        var invalids = validateForm(form);
        if (invalids.length) {
          e.preventDefault();
          e.stopImmediatePropagation();
          // Підсвічуємо ВСІ проблемні поля (toast рахує саме їх), і кожне
          // далі перевіряється на кожному вводі.
          invalids.forEach(function (item, i) {
            if (item.el.matches('input, select, textarea')) live.add(item.el);
            if (i > 0) showFieldError(item.el, item.msg, true);
          });
          focusInvalid(invalids[0]);
          notify(
            invalids.length === 1
              ? t('Перевірте форму: {count} поле потребує уваги', { count: invalids.length })
              : t('Перевірте форму: {count} поля(ів) потребують уваги', { count: invalids.length }),
            'warning'
          );
        }
      }, true);

      // --- blur: перевіряємо поле, яке користувач залишає ------------------
      // focusout (а не blur) -- щоб працювала делегація на рівні форми.
      form.addEventListener('focusout', function (e) {
        var field = e.target;
        if (!field.matches || !field.matches('input, select, textarea')) return;
        if (field.type === 'radio' || field.type === 'checkbox' || field.type === 'hidden') return;
        if (!touched.has(field) && !live.has(field)) return;   // просто протабав -- мовчимо

        var msg = fieldError(field);
        if (msg) {
          live.add(field);
          showFieldError(field, msg);
        } else if (canConfirm(field)) {
          showFieldOk(field);
        } else {
          clearFieldState(field);
        }
      });

      // --- input: live-режим після помилки ---------------------------------
      form.addEventListener('input', function (e) {
        var field = e.target;
        if (!field.matches || !field.matches('input, select, textarea')) return;
        touched.add(field);
        clearServerError(field);

        var group = field.closest('[data-required-group]');
        if (group) {
          group.classList.remove('field-invalid');
          var h = group.querySelector('.field-hint--js');
          if (h) h.remove();
        }

        if (!live.has(field)) {
          // Ще не помилялось: не заважаємо набирати, лише знімаємо
          // позитивний стан, доки поле не перевірене повторно на blur.
          if (field.classList.contains('field-valid')) clearFieldState(field);
          return;
        }

        // Виправив -- одразу підтверджуємо. Ще ні -- лишаємо стару підказку
        // (нову помилку під час набору не показуємо), але знімаємо галочку:
        // «виглядає добре» над невалідним значенням -- гірше за мовчання.
        refreshLive(field);

        // Пара «пароль / підтвердження»: перевіряємо і залежне поле.
        form.querySelectorAll('[data-match]').forEach(function (dep) {
          if (dep !== field && live.has(dep)) refreshLive(dep);
        });
      });

      form.addEventListener('change', function (e) {
        var field = e.target;
        if (!field.matches) return;
        if (field.matches('input[type="radio"], input[type="checkbox"]')) {
          var group = field.closest('[data-required-group]');
          if (group) {
            group.classList.remove('field-invalid');
            var h = group.querySelector('.field-hint--js');
            if (h) h.remove();
          } else {
            clearFieldError(field);
          }
          return;
        }
        // select та автозаповнення браузера: input не завжди спрацьовує
        if (field.matches('select, input, textarea')) {
          touched.add(field);
          clearServerError(field);
          if (live.has(field)) refreshLive(field);
        }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFormValidation);
  } else {
    initFormValidation();
  }
})();
