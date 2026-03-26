/* settings.js -- перемикачі теми та шрифту */
(function () {
  var THEME_KEY = 'iprm-theme';
  var FONT_KEY = 'iprm-font';

  function storageGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function storageSet(key, val) {
    try { localStorage.setItem(key, val); } catch (e) { /* private mode */ }
  }

  function getTheme() {
    return storageGet(THEME_KEY) === 'branded' ? 'branded' : 'legacy';
  }

  function getFont() {
    return storageGet(FONT_KEY) === 'fixel' ? 'fixel' : 'inter';
  }

  function applyTheme(theme) {
    if (theme === 'branded') {
      document.documentElement.setAttribute('data-theme', 'branded');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    storageSet(THEME_KEY, theme);
    markActive('data-theme-select', theme);
  }

  function applyFont(font) {
    if (font === 'fixel') {
      document.documentElement.setAttribute('data-font', 'fixel');
    } else {
      document.documentElement.removeAttribute('data-font');
    }
    storageSet(FONT_KEY, font);
    markActive('data-font-select', font);
  }

  function markActive(attr, value) {
    var buttons = document.querySelectorAll('[' + attr + ']');
    buttons.forEach(function (btn) {
      btn.classList.toggle('is-active', btn.getAttribute(attr) === value);
    });
  }

  /* Ініціалізація */
  markActive('data-theme-select', getTheme());
  markActive('data-font-select', getFont());

  /* Обробники кліків */
  document.querySelectorAll('[data-theme-select]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      applyTheme(this.getAttribute('data-theme-select'));
    });
  });

  document.querySelectorAll('[data-font-select]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      applyFont(this.getAttribute('data-font-select'));
    });
  });
})();
