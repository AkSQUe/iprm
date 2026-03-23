(function () {
  var STORAGE_KEY = 'iprm-theme';
  var THEMES = ['legacy', 'branded'];
  var LABELS = { legacy: 'Legacy', branded: 'Branded' };

  function getTheme() {
    var saved = localStorage.getItem(STORAGE_KEY);
    return THEMES.indexOf(saved) !== -1 ? saved : 'legacy';
  }

  function applyTheme(theme) {
    if (theme === 'legacy') {
      document.documentElement.removeAttribute('data-theme');
    } else {
      document.documentElement.setAttribute('data-theme', theme);
    }
    localStorage.setItem(STORAGE_KEY, theme);

    var buttons = document.querySelectorAll('.theme-toggle');
    for (var i = 0; i < buttons.length; i++) {
      var label = buttons[i].querySelector('.theme-toggle__label');
      if (label) {
        label.textContent = LABELS[theme] || theme;
      }
    }
  }

  function toggle() {
    var current = getTheme();
    var next = current === 'legacy' ? 'branded' : 'legacy';
    applyTheme(next);
  }

  // Apply saved theme immediately (before DOM ready) to prevent flash
  applyTheme(getTheme());

  document.addEventListener('DOMContentLoaded', function () {
    var buttons = document.querySelectorAll('.theme-toggle');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', toggle);
    }
    // Update label after DOM is ready
    applyTheme(getTheme());
  });
})();
