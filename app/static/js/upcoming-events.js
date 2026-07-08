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

  function hide() {
    el.classList.add('upcoming-events--hidden');
    /* Варіант "bar" резервує місце падінгом body -- звільняємо його */
    document.body.classList.remove('has-upcoming-bar');
  }

  try {
    if (window.localStorage && localStorage.getItem(KEY) === signature) {
      hide();
      return;
    }
  } catch (e) {
    /* localStorage недоступний (приватний режим) -- просто показуємо блок */
  }

  var closeBtn = document.getElementById('upcoming-events-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', function () {
      hide();
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
