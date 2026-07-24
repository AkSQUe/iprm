/* Перемикач мовних шарів в адмін-формах (course_edit, trainer_edit,
   blog_edit). Українські поля (канонічні, часто required) видимі завжди;
   кнопки РУС/ENG показують під ними відповідні translation-інпути
   (data-i18n-pane="ru|en"), кнопка УКР ховає всі translation-шари.
   Розмітка: [data-i18n-tabs] з кнопками [data-i18n-lang]. */
(function () {
  'use strict';

  var tabs = document.querySelector('[data-i18n-tabs]');
  if (!tabs) return;

  var buttons = tabs.querySelectorAll('[data-i18n-lang]');
  var panes = document.querySelectorAll('[data-i18n-pane]');

  function activate(lang) {
    panes.forEach(function (pane) {
      pane.classList.toggle(
        'i18n-pane--visible', pane.getAttribute('data-i18n-pane') === lang
      );
    });
    buttons.forEach(function (btn) {
      var active = btn.getAttribute('data-i18n-lang') === lang;
      btn.classList.toggle('i18n-tabs__btn--active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  buttons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      activate(btn.getAttribute('data-i18n-lang'));
    });
  });

  activate('uk');
})();
