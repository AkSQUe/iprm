/* settings.js -- перемикачі шрифту та теми (варіант C: система/світла/тёмна) */
(function () {
  var FONT_KEY = 'iprm-font';
  var THEME_KEY = 'iprm-theme';
  var mql = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function storageGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function storageSet(key, val) {
    try { localStorage.setItem(key, val); } catch (e) { /* private mode */ }
  }

  function markActive(attr, value) {
    document.querySelectorAll('[' + attr + ']').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.getAttribute(attr) === value);
    });
  }

  /* ---------- Шрифт ---------- */
  function getFont() {
    return storageGet(FONT_KEY) === 'fixel' ? 'fixel' : 'inter';
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

  /* ---------- Тема ---------- */
  function getThemeChoice() {
    var t = storageGet(THEME_KEY);
    return (t === 'light' || t === 'dark') ? t : 'system';
  }

  function resolveTheme(choice) {
    if (choice === 'light' || choice === 'dark') return choice;
    return (mql && mql.matches) ? 'dark' : 'light';
  }

  function applyResolvedTheme(resolved) {
    document.documentElement.setAttribute('data-theme', resolved);
    var meta = document.getElementById('meta-theme-color');
    if (meta) meta.setAttribute('content', resolved === 'dark' ? '#131318' : '#f5f5f7');
    /* Повідомляємо canvas-фон (та інших слухачів) перечитати кольори з CSS */
    try { window.dispatchEvent(new CustomEvent('iprm:themechange', { detail: { theme: resolved } })); } catch (e) { /* старий браузер */ }
  }

  function applyTheme(choice) {
    storageSet(THEME_KEY, choice);
    applyResolvedTheme(resolveTheme(choice));
    markActive('data-theme-select', choice);
  }

  /* ---------- Ініціалізація активних станів ---------- */
  markActive('data-font-select', getFont());
  markActive('data-theme-select', getThemeChoice());

  document.querySelectorAll('[data-font-select]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      applyFont(this.getAttribute('data-font-select'));
    });
  });

  document.querySelectorAll('[data-theme-select]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      applyTheme(this.getAttribute('data-theme-select'));
    });
  });

  /* Живе оновлення при зміні системної теми, коли обрано "Система" */
  if (mql) {
    var onSystemChange = function () {
      if (getThemeChoice() === 'system') applyResolvedTheme(resolveTheme('system'));
    };
    if (mql.addEventListener) mql.addEventListener('change', onSystemChange);
    else if (mql.addListener) mql.addListener(onSystemChange);
  }
})();
