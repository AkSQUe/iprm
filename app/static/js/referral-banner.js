/* referral-banner.js -- показ/закриття банера "вас рекомендує".

   Банер у розмітці hidden; показуємо лише коли не закритий раніше
   (localStorage). Закриття запам'ятовується. Vanilla JS, без inline. */
(function () {
  'use strict';
  var KEY = 'iprm_ref_banner_dismissed';

  document.querySelectorAll('[data-referral-banner]').forEach(function (banner) {
    try {
      if (localStorage.getItem(KEY) === '1') return;
    } catch (e) { /* localStorage недоступний -- показуємо банер */ }

    banner.hidden = false;
    var close = banner.querySelector('[data-referral-banner-close]');
    if (close) {
      close.addEventListener('click', function () {
        banner.hidden = true;
        try { localStorage.setItem(KEY, '1'); } catch (e) { /* ignore */ }
      });
    }
  });
})();
