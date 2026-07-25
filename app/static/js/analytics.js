/* analytics.js -- ініціалізація Google Analytics 4 (gtag) + відкладене
   завантаження самого gtag.js.

   Винесено у зовнішній файл (CLAUDE.md: No Inline Policy).

   Тут дві речі:
   1. Ініціалізація dataLayer і `gtag('config', ...)` -- одразу, синхронно.
      Це кілька рядків, вони нічого не важать.
   2. Вставка лоадера gtag.js (~161 KB) -- ПІСЛЯ рендеру. На /blog/ він був
      39% ваги сторінки і відбирав канал у LCP-зображення (62 KB приходили за
      2122 мс замість ~310 мс, які потрібні самому файлу).

   Чому відкладення не губить дані: gtag() тут -- це штатний пушер у
   dataLayer, а gtag.js, завантажившись, програє всю накопичену чергу. Тож
   page_view з `config` і події з ga-events.js, зроблені до приходу лоадера,
   відправляться разом із ним. Втрачаються лише сесії, обірвані до цього
   моменту.

   Тригер -- що настане раніше: подія load, перша взаємодія користувача або
   стеля LOADER_MAX_DELAY_MS (щоб лоадер стартував навіть тоді, коли load
   не настає через якийсь підвислий підресурс).

   ID береться з атрибута `data-ga-id` на цьому ж <script>-тегу, який Jinja
   підставляє з config.GOOGLE_ANALYTICS_ID. Якщо ID порожній -- модуль
   виходить без побічних ефектів. */
(function () {
  'use strict';

  var LOADER_MAX_DELAY_MS = 3000;

  // currentScript доступний під час синхронного виконання модуля.
  var cur = document.currentScript || document.querySelector('script[data-ga-id]');
  if (!cur) return;
  var id = cur.getAttribute('data-ga-id');
  if (!id) return;

  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag('js', new Date());

  // First-party транспорт: маяки collect шлемо на власний домен (nginx
  // проксує їх на google-analytics.com), щоб оминути блокувальники.
  var transport = cur.getAttribute('data-ga-transport');
  var cfg = {};
  if (transport) {
    cfg.transport_url = window.location.origin + transport;
    cfg.first_party_collection = true;
  }
  window.gtag('config', id, cfg);

  // ---- відкладена вставка gtag.js ----
  var loaderSrc = cur.getAttribute('data-ga-loader');
  if (!loaderSrc) return;

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
    script.src = loaderSrc;
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
})();
