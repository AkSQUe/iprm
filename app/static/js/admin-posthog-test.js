/* admin-posthog-test.js -- перевірка PostHog з боку браузера.

   Сенс саме браузерної перевірки: health-check на сторінці інтеграції
   ходить у PostHog НАПРЯМУ і тому не бачить того єдиного, що ми будували
   самі -- first-party проксі. Тут запити йдуть тим самим шляхом, що й у
   відвідувачів, тож 404 (немає локацій nginx) чи 401 (загублений Host)
   випливають одразу.

   Три перевірки:
     1. /ngx-e/static/array.js  -- SDK віддається через проксі;
     2. /ngx-e/array/<key>/config.js -- ремоут-конфіг (без нього реплей
        мовчки не працює, хоча події йдуть);
     3. window.posthog з методом capture -- SDK справді ініціалізувався. */
(function () {
  'use strict';

  var cur = document.currentScript
    || document.querySelector('script[data-ph-api-host]');
  if (!cur) return;

  var apiHost = cur.getAttribute('data-ph-api-host') || '/ngx-e';
  var key = cur.getAttribute('data-ph-key') || '';

  function setCell(id, text, ok) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.classList.toggle('is-ok', ok === true);
    el.classList.toggle('is-error', ok === false);
  }

  function say(text) {
    var el = document.getElementById('ph-test-result');
    if (el) el.textContent = text;
  }

  /* HEAD, а не GET: тіло array.js важить сотні кілобайт, а нас цікавить
     лише статус і те, що віддається саме JavaScript. */
  function probe(id, url, label) {
    fetch(url, { method: 'HEAD', cache: 'no-store' })
      .then(function (r) {
        var type = r.headers.get('content-type') || '';
        if (!r.ok) {
          setCell(id, r.status + ' ' + r.statusText, false);
          return;
        }
        // 200 з HTML замість JS означає, що запит підхопила локація
        // застосунку, а не проксі -- тобто сніпет nginx не застосований.
        if (type.indexOf('javascript') === -1) {
          setCell(id, '200, але content-type: ' + (type || 'невідомий'), false);
          return;
        }
        setCell(id, '200 OK', true);
      })
      .catch(function (e) {
        setCell(id, 'запит не пройшов: ' + (e && e.message ? e.message : e), false);
      });
  }

  probe('ph-check-static', apiHost + '/static/array.js', 'SDK');
  if (key) {
    probe('ph-check-array', apiHost + '/array/' + key + '/config.js', 'конфіг');
  } else {
    setCell('ph-check-array', 'ключ невідомий', false);
  }

  /* SDK вантажиться ліниво (див. posthog.js), тож одразу після рендеру його
     ще немає -- це нормально, а не помилка. Тому опитуємо з інтервалом і
     здаємося лише після стелі. */
  var SDK_TIMEOUT_MS = 8000;
  var started = Date.now();
  var poll = window.setInterval(function () {
    if (window.posthog && typeof window.posthog.capture === 'function'
        && window.posthog.__SV !== 1) {
      window.clearInterval(poll);
      setCell('ph-check-sdk', 'завантажено', true);
      return;
    }
    if (Date.now() - started > SDK_TIMEOUT_MS) {
      window.clearInterval(poll);
      // Стаб-черга є завжди; якщо справжній SDK так і не приїхав, виклики
      // осядуть у ній і нікуди не підуть.
      setCell('ph-check-sdk', 'не завантажився (лишилась черга-заглушка)', false);
    }
  }, 250);

  var btn = document.getElementById('ph-test-send');
  if (!btn) return;
  btn.addEventListener('click', function () {
    if (!window.posthog || typeof window.posthog.capture !== 'function') {
      say('SDK ще не готовий -- зачекайте кілька секунд і спробуйте знову.');
      return;
    }
    window.posthog.capture('IPRMTestEvent', {
      source: 'admin_test_page',
      sent_at: new Date().toISOString(),
    });
    say('Подію IPRMTestEvent надіслано. Шукайте її в PostHog -> Activity '
      + '(зазвичай приходить за кілька секунд).');
  });
})();
