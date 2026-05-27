/* ui-feedback.js — глобальні UX-компоненти ІПРМ:
   1) Toast-нотифікації (window.iprmToast)
   2) Клієнтська валідація форм [data-validate] зі scroll/анімацією/підказкою
   3) Tooltips на [data-tooltip]

   Vanilla JS, без залежностей. Progressive enhancement: форми працюють і
   без JS (server-side WTForms-валідація лишається). */
(function () {
  'use strict';

  // =====================================================================
  // 1. TOASTS
  // =====================================================================
  var TOAST_ICONS = {
    success: '✓',   // ✓
    error: '✕',     // ✕
    warning: '⚠',   // ⚠
    info: 'ℹ',      // ℹ
  };
  var TOAST_TITLES = {
    success: 'Готово',
    error: 'Помилка',
    warning: 'Увага',
    info: 'Інформація',
  };

  var _container = null;

  function getContainer() {
    if (_container && document.body.contains(_container)) return _container;
    _container = document.querySelector('.iprm-toasts');
    if (!_container) {
      _container = document.createElement('div');
      _container.className = 'iprm-toasts';
      _container.setAttribute('aria-live', 'polite');
      _container.setAttribute('aria-atomic', 'false');
      document.body.appendChild(_container);
    }
    return _container;
  }

  /**
   * Показати toast.
   * @param {string} message
   * @param {('success'|'error'|'warning'|'info')} [type='info']
   * @param {{duration?:number, title?:string}} [opts]
   */
  function showToast(message, type, opts) {
    type = TOAST_ICONS[type] ? type : 'info';
    opts = opts || {};
    var duration = typeof opts.duration === 'number'
      ? opts.duration
      : (type === 'error' ? 7000 : 4500);
    var title = opts.title != null ? opts.title : TOAST_TITLES[type];

    var el = document.createElement('div');
    el.className = 'iprm-toast iprm-toast--' + type;
    el.setAttribute('role', type === 'error' ? 'alert' : 'status');

    el.innerHTML =
      '<span class="iprm-toast__icon" aria-hidden="true">' + TOAST_ICONS[type] + '</span>' +
      '<div class="iprm-toast__body">' +
        (title ? '<p class="iprm-toast__title"></p>' : '') +
        '<p class="iprm-toast__msg"></p>' +
      '</div>' +
      '<button type="button" class="iprm-toast__close" aria-label="Закрити">✕</button>';

    if (title) el.querySelector('.iprm-toast__title').textContent = title;
    el.querySelector('.iprm-toast__msg').textContent = message;

    var container = getContainer();
    container.appendChild(el);

    // reflow → клас .is-visible для CSS-анімації входу
    requestAnimationFrame(function () { el.classList.add('is-visible'); });

    var timer = null;
    function dismiss() {
      if (!el.parentNode) return;
      el.classList.remove('is-visible');
      el.classList.add('is-leaving');
      el.addEventListener('transitionend', function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, { once: true });
      // fallback на випадок якщо transitionend не спрацює
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 600);
    }

    el.querySelector('.iprm-toast__close').addEventListener('click', dismiss);
    if (duration > 0) {
      timer = setTimeout(dismiss, duration);
      // пауза автозакриття при наведенні
      el.addEventListener('mouseenter', function () { clearTimeout(timer); });
      el.addEventListener('mouseleave', function () { timer = setTimeout(dismiss, 2000); });
    }
    return el;
  }

  window.iprmToast = showToast;

  // Flash → toast bridge: читаємо server-side flash-повідомлення з
  // hidden JSON-блоку (base.html) і показуємо як toasts.
  function bootstrapFlashes() {
    var node = document.getElementById('iprm-flash-data');
    if (!node) return;
    var flashes;
    try {
      flashes = JSON.parse(node.textContent || '[]');
    } catch (e) {
      return;
    }
    // map Flask-категорій на наші типи
    var typeMap = { message: 'info', error: 'error', success: 'success', info: 'info', warning: 'warning' };
    flashes.forEach(function (f, i) {
      var type = typeMap[f.category] || 'info';
      // легкий стагер щоб toasts не злипались
      setTimeout(function () { showToast(f.message, type); }, i * 250);
    });
  }

  // =====================================================================
  // 2. FORM VALIDATION ([data-validate])
  // =====================================================================
  var HINT_DEFAULT = 'Будь ласка, заповніть це поле';
  var HINT_BY_TYPE = {
    email: 'Вкажіть коректну адресу електронної пошти',
    tel: 'Вкажіть номер телефону',
    date: 'Оберіть дату',
    checkbox: 'Необхідно поставити цю позначку',
  };

  function clearFieldError(field) {
    var group = field.closest('.form-group, .reg-form-section, .form-consent') || field.parentNode;
    field.classList.remove('field-invalid');
    var hint = group.querySelector('.field-hint--js');
    if (hint) hint.remove();
  }

  function showFieldError(field, message, anchorEl) {
    var anchor = anchorEl || field;
    var group = anchor.closest('.form-group, .reg-form-section, .form-consent') || anchor.parentNode;

    // не дублюємо
    var existing = group.querySelector('.field-hint--js');
    if (existing) existing.remove();

    var hint = document.createElement('div');
    hint.className = 'field-hint field-hint--js';
    hint.setAttribute('role', 'alert');
    hint.textContent = message;
    group.appendChild(hint);

    anchor.classList.add('field-invalid');
    // знімаємо анімацію після відтворення щоб можна було тригерити повторно
    anchor.addEventListener('animationend', function () {
      anchor.classList.remove('field-shake');
    }, { once: true });
    anchor.classList.add('field-shake');
  }

  function firstFocusable(el) {
    // для radio/checkbox-груп фокусуємось на першому input
    if (el.matches('input, select, textarea')) return el;
    return el.querySelector('input, select, textarea') || el;
  }

  function validateForm(form) {
    var invalids = [];

    // 2.1 Стандартні поля з [required] / HTML5-валідацією
    var fields = form.querySelectorAll('input[required], select[required], textarea[required], input[data-required], select[data-required], textarea[data-required]');
    fields.forEach(function (field) {
      // radio/checkbox обробляємо у групах нижче — пропускаємо тут
      if (field.type === 'radio' || field.type === 'checkbox') return;
      clearFieldError(field);
      if (!field.value || (field.checkValidity && !field.checkValidity())) {
        var hint = HINT_BY_TYPE[field.type] || HINT_DEFAULT;
        if (field.value && field.validationMessage) {
          // значення є, але формат невалідний (email/date)
          hint = HINT_BY_TYPE[field.type] || field.validationMessage;
        }
        invalids.push({ el: field, msg: hint });
      }
    });

    // 2.2 Обов'язкова одиночна checkbox (згода)
    form.querySelectorAll('input[type="checkbox"][required], input[type="checkbox"][data-required]').forEach(function (cb) {
      clearFieldError(cb);
      if (!cb.checked) {
        invalids.push({ el: cb, msg: cb.getAttribute('data-hint') || HINT_BY_TYPE.checkbox });
      }
    });

    // 2.3 Групи: radio / checkbox з [data-required-group]
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
    var target = item.isGroup ? item.el : item.el;
    var scrollTarget = target.closest('.form-group, .reg-form-section, .form-consent') || target;

    scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });

    showFieldError(item.el, item.msg);

    // фокус після прокрутки (невеликий delay щоб smooth-scroll стартував)
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

      // Capture-фаза + stopImmediatePropagation: гарантує що наш валідатор
      // спрацює ПЕРШИМ і, при помилці, заблокує bubble-listener
      // form-single-submit.js (інакше кнопка залишилась би disabled назавжди).
      form.addEventListener('submit', function (e) {
        var invalids = validateForm(form);
        if (invalids.length) {
          e.preventDefault();
          e.stopImmediatePropagation();
          focusInvalid(invalids[0]);
          showToast(
            'Перевірте форму: ' + invalids.length +
            (invalids.length === 1 ? ' поле потребує уваги' : ' поля(ів) потребують уваги'),
            'warning'
          );
        }
      }, true);

      // realtime: знімаємо помилку коли користувач виправляє поле
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

  // =====================================================================
  // 3. TOOLTIPS ([data-tooltip])
  // =====================================================================
  function initTooltips() {
    var triggers = document.querySelectorAll('[data-tooltip]');
    triggers.forEach(function (trigger) {
      if (trigger.__iprmTooltipBound) return;
      trigger.__iprmTooltipBound = true;

      trigger.setAttribute('tabindex', trigger.getAttribute('tabindex') || '0');
      trigger.setAttribute('role', 'button');
      trigger.setAttribute('aria-label', 'Підказка: ' + trigger.getAttribute('data-tooltip'));

      var bubble = null;

      function show() {
        if (bubble) return;
        bubble = document.createElement('span');
        bubble.className = 'iprm-tooltip-bubble';
        bubble.textContent = trigger.getAttribute('data-tooltip');
        document.body.appendChild(bubble);
        var r = trigger.getBoundingClientRect();
        var top = window.scrollY + r.top - bubble.offsetHeight - 10;
        var left = window.scrollX + r.left + r.width / 2 - bubble.offsetWidth / 2;
        // не вилазити за лівий край
        left = Math.max(8, left);
        // якщо зверху не влазить — показати знизу
        if (top < window.scrollY + 4) {
          top = window.scrollY + r.bottom + 10;
          bubble.classList.add('iprm-tooltip-bubble--below');
        }
        bubble.style.top = top + 'px';
        bubble.style.left = left + 'px';
        requestAnimationFrame(function () { if (bubble) bubble.classList.add('is-visible'); });
      }
      function hide() {
        if (!bubble) return;
        var b = bubble;
        bubble = null;
        b.classList.remove('is-visible');
        setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 200);
      }

      trigger.addEventListener('mouseenter', show);
      trigger.addEventListener('mouseleave', hide);
      trigger.addEventListener('focus', show);
      trigger.addEventListener('blur', hide);
      trigger.addEventListener('click', function (e) {
        e.preventDefault();
        if (bubble) hide(); else show();
      });
    });
  }

  // =====================================================================
  // INIT
  // =====================================================================
  function init() {
    bootstrapFlashes();
    initFormValidation();
    initTooltips();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
