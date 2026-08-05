/* meta-pixel.js -- ініціалізація Meta (Facebook) Pixel + відкладене
   завантаження fbevents.js.

   Канонічний snippet від Meta -- inline; тут він винесений у зовнішній файл
   (CLAUDE.md: No Inline Policy) і розбитий на дві частини, за зразком
   analytics.js:

   1. Черга fbq -- одразу, синхронно. Кілька рядків, нічого не важать.
      fbq('init', id) і fbq('track', 'PageView') лягають у чергу
      fbq.queue навіть до приходу лоадера.
   2. Вставка fbevents.js (~90 KB) -- ПІСЛЯ рендеру. Той самий мотив, що з
      gtag.js: на сторінках з важким LCP-зображенням сторонній скрипт
      відбирає канал саме тоді, коли він потрібен контенту.

   Чому відкладення не губить дані: fbq до завантаження -- це штатний пушер
   у fbq.queue (така сама механіка, як у самого snippet'а Meta), а
   fbevents.js, завантажившись, програє чергу. Тож PageView і події з
   meta-events.js, зроблені до приходу лоадера, відправляться разом із ним.

   Тригер -- що настане раніше: подія load, перша взаємодія користувача або
   стеля LOADER_MAX_DELAY_MS (щоб лоадер стартував навіть тоді, коли load
   не настає через якийсь підвислий підресурс).

   ID береться з атрибута data-pixel-id на цьому ж <script>-тегу, який Jinja
   підставляє з site_settings.effective_meta_pixel_id. Якщо ID порожній --
   модуль виходить без побічних ефектів. */
(function () {
  'use strict';

  var LOADER_MAX_DELAY_MS = 3000;
  var LOADER_SRC = 'https://connect.facebook.net/en_US/fbevents.js';

  // currentScript доступний під час синхронного виконання модуля.
  var cur = document.currentScript || document.querySelector('script[data-pixel-id]');
  if (!cur) return;
  var id = cur.getAttribute('data-pixel-id');
  if (!id) return;

  init();

  function init() {
    // Черга-заглушка -- один в один з офіційним snippet'ом Meta: після
    // завантаження fbevents.js він бачить fbq.queue і програє її.
    if (!window.fbq) {
      var n = function () {
        n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments);
      };
      n.push = n;
      n.loaded = true;
      n.version = '2.0';
      n.queue = [];
      window.fbq = n;
      if (!window._fbq) window._fbq = n;
    }

    /* Automatic Advanced Matching -- вимикаємо явно.
       Це налаштування кабінету Meta: коли воно увімкнене, fbevents.js сам
       вичитує з форм email і телефон і шле їх у хешованому вигляді. Наша
       Політика конфіденційності стверджує, що ці дані до Meta не
       передаються, тож обіцянку мусить тримати код, а не перемикач у
       чужому кабінеті, який хтось може ввімкнути не думаючи.
       Порядок важливий: перед init, інакше autoConfig уже застосується. */
    window.fbq('set', 'autoConfig', false, id);

    window.fbq('init', id);
    window.fbq('track', 'PageView');

    scheduleLoader();
  }

  // ---- відкладена вставка fbevents.js ----
  function scheduleLoader() {
    var events = ['pointerdown', 'keydown', 'touchstart'];
    var timer = null;
    var started = false;

    function detach() {
      window.removeEventListener('load', start);
      events.forEach(function (name) {
        window.removeEventListener(name, start, true);
      });
      if (timer) {
        window.clearTimeout(timer);
        timer = null;
      }
    }

    function start() {
      if (started) return;
      started = true;
      detach();
      var script = document.createElement('script');
      script.async = true;
      script.src = LOADER_SRC;
      document.head.appendChild(script);
    }

    if (document.readyState === 'complete') {
      start();
    } else {
      window.addEventListener('load', start);
      events.forEach(function (name) {
        window.addEventListener(name, start, true);
      });
      timer = window.setTimeout(start, LOADER_MAX_DELAY_MS);
    }
  }
})();
