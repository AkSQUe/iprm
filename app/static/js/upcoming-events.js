/* Плаваючий блок "найближчі заходи": закриття з памʼяттю у localStorage.
 * Памʼятаємо ПІДПИС показаних заходів (id через дефіс) -- щойно зʼявляються
 * інші заходи, підпис змінюється й блок показується знову. */
(function () {
  'use strict';
  var KEY = 'iprm-upcoming-dismissed';
  var el = document.getElementById('upcoming-events');
  if (!el) {
    return;
  }
  var signature = el.getAttribute('data-signature') || '';

  try {
    if (window.localStorage && localStorage.getItem(KEY) === signature) {
      el.classList.add('upcoming-events--hidden');
      return;
    }
  } catch (e) {
    /* localStorage недоступний (приватний режим) -- просто показуємо блок */
  }

  var closeBtn = document.getElementById('upcoming-events-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', function () {
      el.classList.add('upcoming-events--hidden');
      try {
        if (window.localStorage) {
          localStorage.setItem(KEY, signature);
        }
      } catch (e) {
        /* ignore */
      }
    });
  }
})();
