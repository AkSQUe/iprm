/* copy-to-clipboard.js — копіювання в буфер з toast-підтвердженням.

   Розмітка:  <button data-copy="текст для копіювання">...</button>
   Якщо data-copy порожній — копіюється textContent елемента.

   Опціонально використовує window.iprmToast (toast.js) для фідбеку.
   Vanilla JS. Single Responsibility. */
(function () {
  'use strict';

  function notify(text, ok) {
    if (typeof window.iprmToast !== 'function') return;
    if (ok) {
      window.iprmToast('Скопійовано: ' + text, 'success', { duration: 2500 });
    } else {
      window.iprmToast('Не вдалося скопіювати', 'error', { duration: 2500 });
    }
  }

  function legacyCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }

  function copy(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { notify(text, true); },
        function () { notify(text, legacyCopy(text)); }
      );
    } else {
      notify(text, legacyCopy(text));
    }
  }

  function init() {
    document.querySelectorAll('[data-copy]').forEach(function (el) {
      if (el.__iprmCopyBound) return;
      el.__iprmCopyBound = true;
      el.addEventListener('click', function (e) {
        e.preventDefault();
        var text = (el.getAttribute('data-copy') || el.textContent || '').trim();
        if (text) copy(text);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
