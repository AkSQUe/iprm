/* Cookie consent banner */
(function() {
  'use strict';
  if (localStorage.getItem('iprm-cookie-consent')) return;
  var banner = document.getElementById('cookie-banner');
  banner.hidden = false;
  document.getElementById('cookie-accept').addEventListener('click', function() {
    localStorage.setItem('iprm-cookie-consent', 'all');
    banner.hidden = true;
  });
  document.getElementById('cookie-reject').addEventListener('click', function() {
    localStorage.setItem('iprm-cookie-consent', 'essential');
    banner.hidden = true;
  });
})();
