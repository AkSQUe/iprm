/* form-validate.js — клієнтська валідація форм [data-validate].

   Поведінка при submit невалідної форми:
     - scroll до першого проблемного поля (smooth, по центру)
     - підсвічування + shake-анімація
     - інлайн-підказка під полем
     - focus
     - toast (якщо доступний window.iprmToast з toast.js)

   Підтримка груп radio/checkbox через [data-required-group] + [data-hint].
   Realtime: помилка знімається коли користувач виправляє поле.

   Залежність (опціональна): toast.js для нотифікації «Перевірте форму».
   Single Responsibility: лише валідація. */
(function () {
  'use strict';

  var HINT_DEFAULT = 'Будь ласка, заповніть це поле';
  var HINT_BY_TYPE = {
    email: 'Вкажіть коректну адресу електронної пошти',
    tel: 'Вкажіть номер телефону',
    date: 'Оберіть дату',
    checkbox: 'Необхідно поставити цю позначку',
  };

  function notify(message, type) {
    if (typeof window.iprmToast === 'function') {
      window.iprmToast(message, type);
    }
  }

  function clearFieldError(field) {
    var group = field.closest('.form-group, .reg-form-section, .form-consent') || field.parentNode;
    field.classList.remove('field-invalid');
    var hint = group.querySelector('.field-hint--js');
    if (hint) hint.remove();
  }

  function showFieldError(field, message, anchorEl) {
    var anchor = anchorEl || field;
    var group = anchor.closest('.form-group, .reg-form-section, .form-consent') || anchor.parentNode;

    var existing = group.querySelector('.field-hint--js');
    if (existing) existing.remove();

    var hint = document.createElement('div');
    hint.className = 'field-hint field-hint--js';
    hint.setAttribute('role', 'alert');
    hint.textContent = message;
    group.appendChild(hint);

    anchor.classList.add('field-invalid');
    anchor.addEventListener('animationend', function () {
      anchor.classList.remove('field-shake');
    }, { once: true });
    anchor.classList.add('field-shake');
  }

  function firstFocusable(el) {
    if (el.matches('input, select, textarea')) return el;
    return el.querySelector('input, select, textarea') || el;
  }

  function validateForm(form) {
    var invalids = [];

    // Стандартні поля з [required] / HTML5
    var fields = form.querySelectorAll('input[required], select[required], textarea[required], input[data-required], select[data-required], textarea[data-required]');
    fields.forEach(function (field) {
      if (field.type === 'radio' || field.type === 'checkbox') return;
      clearFieldError(field);
      if (!field.value || (field.checkValidity && !field.checkValidity())) {
        var hint = HINT_BY_TYPE[field.type] || HINT_DEFAULT;
        if (field.value && field.validationMessage) {
          hint = HINT_BY_TYPE[field.type] || field.validationMessage;
        }
        invalids.push({ el: field, msg: hint });
      }
    });

    // Обов'язкова одиночна checkbox (згода)
    form.querySelectorAll('input[type="checkbox"][required], input[type="checkbox"][data-required]').forEach(function (cb) {
      clearFieldError(cb);
      if (!cb.checked) {
        invalids.push({ el: cb, msg: cb.getAttribute('data-hint') || HINT_BY_TYPE.checkbox });
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
          msg: group.getAttribute('data-hint') || 'Оберіть хоча б один варіант',
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

      // Capture-фаза + stopImmediatePropagation: спрацьовуємо ПЕРШИМИ і при
      // помилці блокуємо bubble-listener form-single-submit.js (інакше
      // кнопка лишилась би disabled назавжди).
      form.addEventListener('submit', function (e) {
        var invalids = validateForm(form);
        if (invalids.length) {
          e.preventDefault();
          e.stopImmediatePropagation();
          focusInvalid(invalids[0]);
          notify(
            'Перевірте форму: ' + invalids.length +
            (invalids.length === 1 ? ' поле потребує уваги' : ' поля(ів) потребують уваги'),
            'warning'
          );
        }
      }, true);

      form.addEventListener('input', function (e) {
        var t = e.target;
        if (t.matches && t.matches('input, select, textarea')) {
          clearFieldError(t);
          var group = t.closest('[data-required-group]');
          if (group) {
            group.classList.remove('field-invalid');
            var h = group.querySelector('.field-hint--js');
            if (h) h.remove();
          }
        }
      });
      form.addEventListener('change', function (e) {
        var t = e.target;
        if (t.matches && t.matches('input[type="radio"], input[type="checkbox"]')) {
          var group = t.closest('[data-required-group]');
          if (group) {
            group.classList.remove('field-invalid');
            var h = group.querySelector('.field-hint--js');
            if (h) h.remove();
          } else {
            clearFieldError(t);
          }
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
