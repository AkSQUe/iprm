/* settings.js -- перемикач шрифту (сторінка налаштувань).
   Тему обробляє глобальний theme.js (єдине runtime-джерело істини). */
(function () {
  var FONT_KEY = 'iprm-font';

  function storageGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function storageSet(key, val) {
    try { localStorage.setItem(key, val); } catch (e) { /* private mode */ }
  }

  function getFont() {
    return storageGet(FONT_KEY) === 'fixel' ? 'fixel' : 'inter';
  }

  function markActive(font) {
    document.querySelectorAll('[data-font-select]').forEach(function (btn) {
      var active = btn.getAttribute('data-font-select') === font;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function applyFont(font) {
    if (font === 'fixel') {
      document.documentElement.setAttribute('data-font', 'fixel');
    } else {
      document.documentElement.removeAttribute('data-font');
    }
    storageSet(FONT_KEY, font);
    markActive(font);
  }

  markActive(getFont());

  document.querySelectorAll('[data-font-select]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      applyFont(this.getAttribute('data-font-select'));
    });
  });
})();
