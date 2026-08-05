/* Cookie notice -- інформаційна заглушка (не гейтить збір даних).

   Банер лише повідомляє про використання cookie; аналітика і маркетингові
   скрипти працюють незалежно від дії користувача. Кнопка просто ховає
   банер і запам'ятовує це, щоб він не з'являвся повторно. */
(function() {
  'use strict';
  var STORAGE_KEY = 'iprm-cookie-consent';

  /* Доступ до localStorage кидає SecurityError, коли сховище заблоковано
     (Safari "Block all cookies", частина корпоративних політик). Без
     try/catch виняток обірвав би модуль -- і банер не показався б узагалі. */
  function read() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function write(value) {
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch (e) {
      // Вибір не переживе перезавантаження -- банер з'явиться знову.
    }
  }

  if (read()) return;
  var banner = document.getElementById('cookie-banner');
  if (!banner) return;
  banner.hidden = false;
  var accept = document.getElementById('cookie-accept');
  if (accept) {
    accept.addEventListener('click', function() {
      write('all');
      banner.hidden = true;
    });
  }
})();
