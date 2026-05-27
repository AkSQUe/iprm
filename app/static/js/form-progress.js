/* form-progress.js — індикатор заповнення форми.

   Розмітка:  <div class="form-progress" data-form-progress="<form-selector>"></div>
   Якщо селектор не задано — береться найближча батьківська форма.
   Рахує частку заповнених обов'язкових полів (включно з radio/checkbox-
   групами [data-required-group] та обов'язковою checkbox-згодою).

   Vanilla JS. Single Responsibility. */
(function () {
  'use strict';

  function init() {
    document.querySelectorAll('[data-form-progress]').forEach(function (bar) {
      var sel = bar.getAttribute('data-form-progress');
      var form = sel ? document.querySelector(sel) : bar.closest('form');
      if (!form) { bar.hidden = true; return; }

      bar.innerHTML =
        '<div class="form-progress__bar"><span></span></div>' +
        '<span class="form-progress__label"></span>';
      var fill = bar.querySelector('.form-progress__bar span');
      var label = bar.querySelector('.form-progress__label');

      function collectFields() {
        var list = [];
        form.querySelectorAll('input[required], select[required], textarea[required]').forEach(function (f) {
          if (f.type === 'radio') return; // радіо рахуємо через групу
          if (f.type === 'checkbox') {
            // одиночна обов'язкова checkbox (згода) — не в групі
            if (!f.closest('[data-required-group]')) list.push(f);
            return;
          }
          list.push(f);
        });
        form.querySelectorAll('[data-required-group]').forEach(function (g) {
          list.push(g);
        });
        return list;
      }

      function isFilled(el) {
        if (el.hasAttribute && el.hasAttribute('data-required-group')) {
          return !!el.querySelector('input:checked');
        }
        if (el.type === 'checkbox') return el.checked;
        return !!(el.value && String(el.value).trim());
      }

      function update() {
        var list = collectFields();
        if (!list.length) { bar.hidden = true; return; }
        var filled = 0;
        list.forEach(function (el) { if (isFilled(el)) filled++; });
        var pct = Math.round(filled / list.length * 100);
        fill.style.width = pct + '%';
        label.textContent = 'Заповнено ' + pct + '%';
        bar.classList.toggle('form-progress--complete', pct === 100);
      }

      form.addEventListener('input', update);
      form.addEventListener('change', update);
      update();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
