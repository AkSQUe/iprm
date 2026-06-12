/* admin-backup.js -- Database backup admin interactions */
(function () {
  'use strict';

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-confirm]');
    if (!btn) return;

    var form = btn.closest('form');
    if (!form) return;

    var message = btn.getAttribute('data-confirm');
    if (!confirm(message)) {
      e.preventDefault();
      e.stopPropagation();
    }
  });
})();
