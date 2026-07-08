/* Плаваюче нагадування "дані для сертифіката не заповнені".
 * Закриття ховає блок до кінця browser-сесії (sessionStorage) --
 * наступного візиту нагадування з'явиться знову, поки анкету не
 * заповнено (навмисний м'який nag, рішення 08.07.2026). */
(function () {
  'use strict';
  var KEY = 'iprm-certdata-dismissed';
  var el = document.getElementById('certdata-reminder');
  if (!el) return;

  try {
    if (window.sessionStorage && sessionStorage.getItem(KEY) === '1') {
      el.hidden = true;
      return;
    }
  } catch (e) {
    /* sessionStorage недоступний -- просто показуємо */
  }

  var closeBtn = document.getElementById('certdata-reminder-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', function () {
      el.hidden = true;
      try {
        if (window.sessionStorage) sessionStorage.setItem(KEY, '1');
      } catch (e) {
        /* ignore */
      }
    });
  }
})();
