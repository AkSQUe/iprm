/* analytics.js -- ініціалізація Google Analytics 4 (gtag).

   Винесено у зовнішній файл (CLAUDE.md: No Inline Policy). Парне до
   <script async src="https://www.googletagmanager.com/gtag/js?id=...">,
   що підвантажує сам gtag.js. Тут лише ініціалізація dataLayer і
   `gtag('config', ...)`.

   ID береться з атрибута `data-ga-id` на цьому ж <script>-тегу, який
   Jinja підставляє з config.GOOGLE_ANALYTICS_ID. Якщо ID порожній --
   модуль виходить без побічних ефектів. */
(function () {
  'use strict';

  // currentScript доступний під час синхронного виконання модуля.
  var cur = document.currentScript || document.querySelector('script[data-ga-id]');
  if (!cur) return;
  var id = cur.getAttribute('data-ga-id');
  if (!id) return;

  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag('js', new Date());
  window.gtag('config', id);
})();
