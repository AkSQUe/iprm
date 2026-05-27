/* password-strength.js — live-індикатор сили пароля.

   Розмітка:  <div class="pw-strength" data-pw-strength-for="<input-id>"></div>
   Модуль сам будує бар + підпис і оновлює їх при вводі.

   Vanilla JS, без залежностей. Single Responsibility. */
(function () {
  'use strict';

  var LEVELS = [
    { label: '', cls: '' },
    { label: 'Слабкий', cls: 'pw-strength--weak' },
    { label: 'Середній', cls: 'pw-strength--medium' },
    { label: 'Хороший', cls: 'pw-strength--good' },
    { label: 'Надійний', cls: 'pw-strength--strong' },
  ];

  function score(pw) {
    if (!pw) return 0;
    var s = 0;
    if (pw.length >= 8) s++;
    if (pw.length >= 12) s++;
    if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
    if (/\d/.test(pw)) s++;
    if (/[^A-Za-z0-9]/.test(pw)) s++;
    return Math.min(s, 4);
  }

  function init() {
    document.querySelectorAll('[data-pw-strength-for]').forEach(function (meter) {
      var input = document.getElementById(meter.getAttribute('data-pw-strength-for'));
      if (!input) return;

      meter.innerHTML =
        '<div class="pw-strength__bar"><span></span></div>' +
        '<span class="pw-strength__label"></span>';
      var bar = meter.querySelector('.pw-strength__bar span');
      var label = meter.querySelector('.pw-strength__label');

      function update() {
        var s = score(input.value);
        var lvl = LEVELS[s];
        meter.className = 'pw-strength' + (lvl.cls ? ' ' + lvl.cls : '');
        bar.style.width = (s / 4 * 100) + '%';
        label.textContent = input.value ? lvl.label : '';
      }

      input.addEventListener('input', update);
      update();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
