/* toast.js — глобальна система toast-нотифікацій ІПРМ.

   Public API:  window.iprmToast(message, type, opts)
     type: 'success' | 'error' | 'warning' | 'info'  (default 'info')
     opts: { duration?: number (ms, 0 = не закривати), title?: string }

   Також піднімає server-side flash-повідомлення з #iprm-flash-data
   (рендериться у base.html) і показує їх як toasts.

   Vanilla JS, без залежностей. Single Responsibility: лише нотифікації. */
(function () {
  'use strict';

  var TOAST_ICONS = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ',
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

    requestAnimationFrame(function () { el.classList.add('is-visible'); });

    var timer = null;
    function dismiss() {
      if (!el.parentNode) return;
      el.classList.remove('is-visible');
      el.classList.add('is-leaving');
      el.addEventListener('transitionend', function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, { once: true });
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 600);
    }

    el.querySelector('.iprm-toast__close').addEventListener('click', dismiss);
    if (duration > 0) {
      timer = setTimeout(dismiss, duration);
      el.addEventListener('mouseenter', function () { clearTimeout(timer); });
      el.addEventListener('mouseleave', function () { timer = setTimeout(dismiss, 2000); });
    }
    return el;
  }

  window.iprmToast = showToast;

  // Flash → toast bridge.
  function bootstrapFlashes() {
    var node = document.getElementById('iprm-flash-data');
    if (!node) return;
    var flashes;
    try {
      flashes = JSON.parse(node.textContent || '[]');
    } catch (e) {
      return;
    }
    var typeMap = { message: 'info', error: 'error', success: 'success', info: 'info', warning: 'warning' };
    flashes.forEach(function (f, i) {
      var type = typeMap[f.category] || 'info';
      setTimeout(function () { showToast(f.message, type); }, i * 250);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapFlashes);
  } else {
    bootstrapFlashes();
  }
})();
