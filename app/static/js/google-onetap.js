/* google-onetap.js — обробка credential від Google One Tap (Phase 6).

   Google's gsi/client підвантажує цей файл лише на сторінках, де є div
   #g_id_onload із data-callback="iprmGoogleOneTap". Цей файл реєструє
   глобальну функцію iprmGoogleOneTap, яку викличе GSI з об'єктом
   {credential: <jwt>}.

   URL endpoint-у читаємо з data-onetap-url на власному <script>-тегу
   (CLAUDE.md: No Inline Policy). При успіху -- редірект на data.next
   (зазвичай /auth/account). При email-collision (409) бекенд повертає
   data.next зі сторінкою-поясненням, як прив'язати Google до наявного
   акаунта.

   Редіректимо лише поки сторінка видима і навігацію ще не почато:
   інакше відповідь One Tap могла обірвати вже запущений redirect-флоу
   (клік по "Увійти через Google" -> перехід на accounts.google.com).
*/
(function () {
  'use strict';

  var script = document.currentScript ||
    document.querySelector('script[data-onetap-url]');
  var endpoint = script && script.getAttribute('data-onetap-url');
  if (!endpoint) return;

  // Взводиться, щойно користувач сам кудись пішов (клік по посиланню,
  // сабміт форми, вивантаження сторінки). Після цього One Tap мовчить:
  // його відповідь не має права перебивати вже початий перехід.
  var navigating = false;
  function markNavigating() { navigating = true; }

  document.addEventListener('click', function (e) {
    var el = e.target.closest && e.target.closest('a[href], button[type="submit"]');
    if (!el) return;
    // Якорі в межах сторінки і посилання в нову вкладку навігацію не
    // починають -- редірект One Tap для них лишається дозволеним.
    if (el.tagName === 'A' &&
        (el.target === '_blank' || el.getAttribute('href').charAt(0) === '#')) return;
    markNavigating();
  }, true);
  document.addEventListener('submit', markNavigating, true);
  window.addEventListener('pagehide', markNavigating);

  function go(url) {
    if (navigating || document.visibilityState === 'hidden') return;
    window.location.href = url;
  }

  window.iprmGoogleOneTap = function (resp) {
    if (!resp || !resp.credential) return;
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ credential: resp.credential })
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    }).then(function (res) {
      if (res.data && res.data.ok) {
        go(res.data.next || window.location.href);
        return;
      }
      // email-collision: сторінка-пояснення, як прив'язати Google до
      // наявного акаунта (увійти паролем -> «Способи входу»).
      if (res.data && res.data.error === 'email_collision' && res.data.next) {
        go(res.data.next);
      }
      // Інші помилки -- мовчки ігноруємо (404/503), щоб не псувати UX
      // на сторінках, де юзер не намагався логінитись.
    }).catch(function (err) {
      console.error('Google One Tap login failed', err);
    });
  };
})();
