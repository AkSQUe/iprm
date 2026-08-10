/* Згортання панелі фільтрів списків адмінки (макрос _filter_bar.html).

   Стан за замовчуванням ставить сервер: панель відкрита, якщо в URL є
   активні фільтри (інакше менеджер керував би зрізом наосліп). Тут -- лише
   ручне перемикання і памʼять вибору між сторінками.

   Памʼять свідомо НЕ перебиває серверний стан: якщо фільтр активний,
   панель лишається відкритою навіть коли минулого разу її згорнули.
   Ключ памʼяті -- id панелі, тож у кожного реєстру свій. */
(function () {
  var STORAGE_PREFIX = 'iprm.admin.filters.';

  function readPref(key) {
    try {
      return window.localStorage.getItem(STORAGE_PREFIX + key);
    } catch (e) {
      return null;  // приватний режим / вимкнені сховища
    }
  }

  function writePref(key, value) {
    try {
      window.localStorage.setItem(STORAGE_PREFIX + key, value);
    } catch (e) {
      /* памʼять -- зручність, а не функція: мовчки живемо без неї */
    }
  }

  function setOpen(panel, toggle, open) {
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  document.querySelectorAll('[data-filter-bar]').forEach(function (bar) {
    var toggle = bar.querySelector('[data-filter-toggle]');
    var panel = bar.querySelector('[data-filter-panel]');
    if (!toggle || !panel) return;

    var key = panel.id || 'default';
    // Сервер уже відкрив панель під активний фільтр -- памʼять не чіпаємо.
    if (panel.hidden && readPref(key) === 'open') {
      setOpen(panel, toggle, true);
    }

    toggle.addEventListener('click', function () {
      var open = panel.hidden;
      setOpen(panel, toggle, open);
      writePref(key, open ? 'open' : 'closed');
      if (open) {
        var first = panel.querySelector('select, input');
        if (first) first.focus();
      }
    });
  });
})();
