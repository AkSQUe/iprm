/* modal.js — відкриття/закриття модалок. Парний до modal.css.

   Розмітка декларативна: кнопка з data-modal-open="<id>" відкриває
   #<id>; будь-який елемент із data-modal-close усередині закриває його.
   Так сторінці не потрібен власний скрипт лише заради показу вікна. */
(function () {
  'use strict';

  var lastTrigger = null;

  function open(id) {
    var el = document.getElementById(id);
    if (!el) { return; }
    el.hidden = false;
    document.body.style.overflow = 'hidden';
    var focusable = el.querySelector(
      'input:not([type=hidden]), select, textarea, button'
    );
    if (focusable) { focusable.focus(); }
  }

  function close(id) {
    var el = document.getElementById(id);
    if (!el) { return; }
    el.hidden = true;
    document.body.style.overflow = '';
    // Фокус назад на кнопку, що відкривала: без цього клавіатурний
    // користувач після Esc опиняється на початку сторінки.
    if (lastTrigger) { lastTrigger.focus(); lastTrigger = null; }
  }

  document.addEventListener('click', function (event) {
    var opener = event.target.closest('[data-modal-open]');
    if (opener) {
      lastTrigger = opener;
      open(opener.getAttribute('data-modal-open'));
      return;
    }
    var closer = event.target.closest('[data-modal-close]');
    if (closer) {
      var host = closer.closest('.modal');
      if (host) { close(host.id); }
    }
  });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') { return; }
    var openModal = document.querySelector('.modal:not([hidden])');
    if (openModal) { close(openModal.id); }
  });

  window.IprmModal = { open: open, close: close };
})();
