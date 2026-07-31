/* Перемикач мовних шарів в адмін-формах (course_edit, trainer_edit,
   blog_edit, course_tariffs). Українські поля (канонічні, часто required)
   видимі завжди; кнопки РУС/ENG показують під ними відповідні
   translation-інпути (data-i18n-pane="ru|en"), кнопка УКР ховає всі
   translation-шари.

   Груп кнопок на сторінці може бути кілька (довга форма курсу -- вкладки
   вгорі й біля блоків програми). Усі групи керують УСІМА панелями сторінки
   і тримаються синхронно: перемикати мову блоку окремо від мови курсу
   безглуздо, а раніше querySelector брав лише першу групу і решта була
   мертвою.

   Обрана мова запам'ятовується: перекладач заповнює форму за формою і не
   мусить щоразу тикати РУС. */
(function () {
  'use strict';

  var STORAGE_KEY = 'iprm.admin.i18nLang';
  var DEFAULT_LANG = 'uk';

  var groups = document.querySelectorAll('[data-i18n-tabs]');
  if (!groups.length) return;

  var panes = document.querySelectorAll('[data-i18n-pane]');

  function readStored() {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;  // приватний режим / вимкнене сховище
    }
  }

  function store(lang) {
    try {
      window.localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) {
      /* не критично -- просто не запам'ятаємо */
    }
  }

  function activate(lang, persist) {
    panes.forEach(function (pane) {
      pane.classList.toggle(
        'i18n-pane--visible', pane.getAttribute('data-i18n-pane') === lang
      );
    });
    groups.forEach(function (group) {
      group.querySelectorAll('[data-i18n-lang]').forEach(function (btn) {
        var active = btn.getAttribute('data-i18n-lang') === lang;
        btn.classList.toggle('i18n-tabs__btn--active', active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
    });
    if (persist) store(lang);
  }

  groups.forEach(function (group) {
    group.querySelectorAll('[data-i18n-lang]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        activate(btn.getAttribute('data-i18n-lang'), true);
      });
    });
  });

  var known = ['uk', 'ru', 'en'];
  var initial = readStored();
  activate(known.indexOf(initial) === -1 ? DEFAULT_LANG : initial, false);
})();
