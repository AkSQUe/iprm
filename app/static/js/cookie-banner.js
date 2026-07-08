/* Cookie notice -- інформаційна заглушка (не гейтить збір даних).

   Банер лише повідомляє про використання cookie; аналітика/збір даних
   працюють незалежно від дії користувача. Кнопка просто ховає банер і
   запам'ятовує це, щоб він не з'являвся повторно. */
(function() {
  'use strict';
  if (localStorage.getItem('iprm-cookie-consent')) return;
  var banner = document.getElementById('cookie-banner');
  if (!banner) return;
  banner.hidden = false;
  var accept = document.getElementById('cookie-accept');
  if (accept) {
    accept.addEventListener('click', function() {
      localStorage.setItem('iprm-cookie-consent', 'all');
      banner.hidden = true;
    });
  }
})();
