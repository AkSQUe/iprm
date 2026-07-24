/* theme.js -- єдине runtime-джерело істини для теми (варіант C: система/світла/тёмна).
   Анти-фликер (pre-paint) робить інлайн-снапшот у <head> base.html. Тут -- реакція на
   зміни ПІСЛЯ завантаження: перемикач у налаштуваннях, системна тема, інші вкладки, bfcache.
   Вантажиться на кожній сторінці, тож "Системна" оновлюється живо всюди, а не лише в налаштуваннях. */
(function () {
  var THEME_KEY = 'iprm-theme';
  var DARK_COLOR = '#131318';
  var LIGHT_COLOR = '#f5f5f7';
  var mql = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function storageGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function storageSet(key, val) {
    try { localStorage.setItem(key, val); } catch (e) { /* private mode */ }
  }

  function getChoice() {
    var t = storageGet(THEME_KEY);
    return (t === 'light' || t === 'dark') ? t : 'system';
  }

  function resolve(choice) {
    if (choice === 'light' || choice === 'dark') return choice;
    return (mql && mql.matches) ? 'dark' : 'light';
  }

  function markActive(choice) {
    document.querySelectorAll('[data-theme-select]').forEach(function (btn) {
      var active = btn.getAttribute('data-theme-select') === choice;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function applyResolved(resolved) {
    document.documentElement.setAttribute('data-theme', resolved);
    var meta = document.getElementById('meta-theme-color');
    if (meta) meta.setAttribute('content', resolved === 'dark' ? DARK_COLOR : LIGHT_COLOR);
    markActive(getChoice());
    /* Повідомляємо canvas-фон (та інших слухачів) перечитати кольори з CSS */
    try {
      window.dispatchEvent(new CustomEvent('iprm:themechange', { detail: { theme: resolved } }));
    } catch (e) { /* старий браузер без CustomEvent-конструктора */ }
  }

  function setChoice(choice) {
    storageSet(THEME_KEY, choice);
    applyResolved(resolve(choice));
  }

  /* Тему до першого рендеру вже виставив інлайн-снапшот; тут лише синхронізуємо
     стан кнопок (aria/is-active) без повторного застосування, щоб не було зайвого
     re-dispatch та мигання. */
  markActive(getChoice());

  document.querySelectorAll('[data-theme-select]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      setChoice(this.getAttribute('data-theme-select'));
    });
  });

  /* Зміна системної теми, коли обрано "Системна" -- на КОЖНІЙ сторінці */
  if (mql) {
    var onSystem = function () {
      if (getChoice() === 'system') applyResolved(resolve('system'));
    };
    if (mql.addEventListener) mql.addEventListener('change', onSystem);
    else if (mql.addListener) mql.addListener(onSystem);
  }

  /* Синхронізація між вкладками */
  window.addEventListener('storage', function (e) {
    if (e.key === THEME_KEY) applyResolved(resolve(getChoice()));
  });

  /* Відновлення з bfcache (back/forward): переобчислюємо на випадок зміни в іншій вкладці */
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) applyResolved(resolve(getChoice()));
  });
})();
