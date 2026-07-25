/* password-strength.js — live-підказка при створенні пароля.

   Розмітка:  <div class="pw-strength" data-pw-strength-for="<input-id>"></div>
   Модуль сам будує сегментний бар, підпис сили і чекліст вимог та оновлює
   їх при кожному вводі.

   Ідея: коуч під час набору замість вироку після submit. Користувач бачить
   зелене ДО натискання кнопки, а не червоне після.

   Обов'язкова тільки довжина (сервер: Length(min=8) -- app/auth/forms.py);
   решта пунктів -- для надійності, тому обов'язковий помічений зірочкою.

   Опції:
     data-pw-no-checklist -- лише бар зі сталою підказкою, без чекліста.

   Vanilla JS, без залежностей. Single Responsibility. */
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

  var MIN_LENGTH = 8;
  var SEGMENTS = 4;

  var LEVELS = [
    { label: '', cls: '' },
    { label: t('Слабкий'), cls: 'pw-strength--weak' },
    { label: t('Середній'), cls: 'pw-strength--medium' },
    { label: t('Хороший'), cls: 'pw-strength--good' },
    { label: t('Надійний'), cls: 'pw-strength--strong' },
  ];

  var RULES = [
    { key: 'len', label: t('{n}+ символів', { n: MIN_LENGTH }), required: true,
      test: function (pw) { return pw.length >= MIN_LENGTH; } },
    { key: 'case', label: t('Велика і мала літери'),
      test: function (pw) { return /[a-zа-яїієґ]/.test(pw) && /[A-ZА-ЯЇІЄҐ]/.test(pw); } },
    { key: 'digit', label: t('Цифра'),
      test: function (pw) { return /\d/.test(pw); } },
    { key: 'symbol', label: t('Спецсимвол'),
      test: function (pw) { return /[^A-Za-zА-Яа-яЇїІіЄєҐґ0-9]/.test(pw); } },
  ];

  function score(pw) {
    if (!pw) return 0;
    var s = 0;
    if (pw.length >= MIN_LENGTH) s++;
    if (pw.length >= 12) s++;
    if (RULES[1].test(pw)) s++;
    if (RULES[2].test(pw)) s++;
    if (RULES[3].test(pw)) s++;
    // Непорожній пароль -- щонайменше «Слабкий»: порожній бар без підпису
    // над трьома набраними символами читається як «індикатор зламався».
    return Math.min(Math.max(s, 1), SEGMENTS);
  }

  function buildMeter() {
    var segments = '';
    for (var i = 0; i < SEGMENTS; i++) segments += '<i class="pw-strength__seg"></i>';
    return '<div class="pw-strength__meter">' +
           '<div class="pw-strength__bar">' + segments + '</div>' +
           '<span class="pw-strength__label" aria-live="polite"></span>' +
           '</div>';
  }

  function buildChecklist() {
    var html = '<ul class="pw-checklist">';
    RULES.forEach(function (rule) {
      html += '<li class="pw-checklist__item" data-pw-rule="' + rule.key + '">' +
              '<span class="pw-checklist__mark" aria-hidden="true"></span>' +
              '<span class="pw-checklist__text">' + rule.label +
              (rule.required ? '<span class="pw-checklist__req" title="' + t("обов'язково") + '">*</span>' : '') +
              '</span>' +
              '<span class="visually-hidden pw-checklist__state"></span>' +
              '</li>';
    });
    return html + '</ul>';
  }

  function init() {
    document.querySelectorAll('[data-pw-strength-for]').forEach(function (block) {
      var input = document.getElementById(block.getAttribute('data-pw-strength-for'));
      if (!input) return;

      var withChecklist = !block.hasAttribute('data-pw-no-checklist');
      block.innerHTML = buildMeter() + (withChecklist ? buildChecklist() : '');

      var segs = block.querySelectorAll('.pw-strength__seg');
      var label = block.querySelector('.pw-strength__label');
      var items = {};
      block.querySelectorAll('.pw-checklist__item').forEach(function (li) {
        items[li.getAttribute('data-pw-rule')] = li;
      });

      var STATE_MET = t('виконано');
      var STATE_UNMET = t('ще ні');

      function update() {
        var pw = input.value;
        var s = score(pw);
        var lvl = LEVELS[s];

        block.className = 'pw-strength' + (lvl.cls ? ' ' + lvl.cls : '');
        // Чекліст показуємо, щойно поле у фокусі: підказка потрібна ДО
        // набору, а не після. Порожнє й розфокусоване -- ховаємо.
        if (pw || document.activeElement === input) block.classList.add('is-shown');
        segs.forEach(function (seg, i) { seg.classList.toggle('is-on', i < s); });
        label.textContent = pw ? lvl.label : '';

        RULES.forEach(function (rule) {
          var li = items[rule.key];
          if (!li) return;
          var met = rule.test(pw);
          li.classList.toggle('is-met', met);
          li.querySelector('.pw-checklist__state').textContent = met ? STATE_MET : STATE_UNMET;
        });
      }

      input.addEventListener('input', update);
      input.addEventListener('focus', function () {
        block.classList.add('is-shown');
      });
      input.addEventListener('blur', function () {
        if (!input.value) block.classList.remove('is-shown');
      });
      update();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
