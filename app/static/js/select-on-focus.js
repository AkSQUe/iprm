/* select-on-focus.js — виділяє весь вміст поля при фокусі/кліку.

   Розмітка:  <input data-select-on-focus ...>

   Зручно для readonly-полів (реферальне посилання тощо), щоб користувач
   міг швидко скопіювати вручну. Vanilla JS. */
(function () {
  'use strict';

  function init() {
    document.querySelectorAll('[data-select-on-focus]').forEach(function (el) {
      if (el.__iprmSelectBound) return;
      el.__iprmSelectBound = true;
      el.addEventListener('focus', function () { el.select(); });
      el.addEventListener('click', function () { el.select(); });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
