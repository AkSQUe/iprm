/* settings.js -- перемикач шрифту (сторінка налаштувань).
   Тему обробляє глобальний theme.js (єдине runtime-джерело істини).

   Список шрифтів дублюється в трьох місцях, і інакше не виходить:
     * тут            -- перевірка збереженого значення;
     * base.html      -- інлайн-антифликер, який має відпрацювати ДО css;
     * common.css     -- блоки [data-font="..."].
   Щоб додати шрифт, треба торкнутись усіх трьох плюс fonts.css. Виносити
   список у спільний JS-файл нема сенсу: антифликеру потрібен саме інлайн,
   інакше шрифт стрибне після завантаження зовнішнього скрипта. */
(function () {
  var FONT_KEY = 'iprm-font';
  var DEFAULT_FONT = 'inter';
  var FONTS = ['inter', 'fixel', 'roboto', 'nunito', 'calibri'];

  function storageGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function storageSet(key, val) {
    try { localStorage.setItem(key, val); } catch (e) { /* private mode */ }
  }

  function getFont() {
    var saved = storageGet(FONT_KEY);
    return FONTS.indexOf(saved) === -1 ? DEFAULT_FONT : saved;
  }

  function markActive(font) {
    document.querySelectorAll('[data-font-select]').forEach(function (btn) {
      var active = btn.getAttribute('data-font-select') === font;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function applyFont(font) {
    if (FONTS.indexOf(font) === -1) { font = DEFAULT_FONT; }
    // Типовий шрифт живе в :root, тож атрибут для нього не потрібен.
    if (font === DEFAULT_FONT) {
      document.documentElement.removeAttribute('data-font');
    } else {
      document.documentElement.setAttribute('data-font', font);
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
