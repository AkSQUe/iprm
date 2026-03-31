/* admin-confirm.js -- confirm dialogs via data-confirm attribute */
/* Replaces inline onsubmit/onclick confirm() calls */
(function () {
  document.addEventListener('submit', function (e) {
    var form = e.target;
    var msg = form.getAttribute('data-confirm');
    if (msg && !confirm(msg)) {
      e.preventDefault();
    }
  });

  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-confirm]');
    if (!el || el.tagName === 'FORM') return;
    var msg = el.getAttribute('data-confirm');
    if (msg && !confirm(msg)) {
      e.preventDefault();
    }
  });

  /* Auto-submit file input (import) */
  document.addEventListener('change', function (e) {
    var el = e.target;
    if (el.classList.contains('admin-file-input')) {
      el.form.submit();
    }
  });
})();
