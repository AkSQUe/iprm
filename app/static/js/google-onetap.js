/* google-onetap.js — обробка credential від Google One Tap (Phase 6).

   Google's gsi/client підвантажує цей файл лише на сторінках, де є div
   #g_id_onload із data-callback="iprmGoogleOneTap". Цей файл реєструє
   глобальну функцію iprmGoogleOneTap, яку викличе GSI з об'єктом
   {credential: <jwt>}.

   URL endpoint-у читаємо з data-onetap-url на власному <script>-тегу
   (CLAUDE.md: No Inline Policy). При успіху -- редірект на data.next
   (зазвичай /auth/account). При email-collision (409) -- на /auth/login,
   де юзер увійде паролем і прив'яже Google вручну в Connections.
*/
(function () {
  'use strict';

  var script = document.currentScript ||
    document.querySelector('script[data-onetap-url]');
  var endpoint = script && script.getAttribute('data-onetap-url');
  if (!endpoint) return;

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
        window.location.href = res.data.next || window.location.href;
        return;
      }
      // email-collision: ведемо на login, щоб юзер увійшов паролем
      // і прив'язав Google вручну в /auth/account/connections.
      if (res.data && res.data.error === 'email_collision' && res.data.login_url) {
        window.location.href = res.data.login_url;
      }
      // Інші помилки -- мовчки ігноруємо (404/503), щоб не псувати UX
      // на сторінках, де юзер не намагався логінитись.
    }).catch(function (err) {
      console.error('Google One Tap login failed', err);
    });
  };
})();
