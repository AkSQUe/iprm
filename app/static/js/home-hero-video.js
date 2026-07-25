/* home-hero-video.js -- фонове відео у hero Головної (progressive enhancement).

   Розмітка віддає лише постер-зображення; сам <video> створюється тут і лише
   тоді, коли це доречно: широкий екран, немає prefers-reduced-motion, немає
   економії трафіку. Так мобільні та повільні з'єднання не тягнуть ~1.6 МБ.
   Vanilla JS. */
(function () {
  'use strict';

  var box = document.querySelector('[data-hero-video]');
  if (!box) return;

  var mq = window.matchMedia;
  if (!mq) return;
  if (mq('(prefers-reduced-motion: reduce)').matches) return;
  if (!mq('(min-width: 768px)').matches) return;
  if (!mq('(hover: hover)').matches) return;

  var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (conn) {
    if (conn.saveData) return;
    var slow = /(^|-)2g$/.test(conn.effectiveType || '');
    if (slow) return;
  }

  var webm = box.getAttribute('data-video-webm');
  var mp4 = box.getAttribute('data-video-mp4');
  if (!webm && !mp4) return;

  var video = document.createElement('video');
  video.className = 'home-hero-media__video';
  video.muted = true;
  video.defaultMuted = true;
  video.loop = true;
  video.playsInline = true;
  video.autoplay = true;
  video.preload = 'auto';
  video.setAttribute('muted', '');
  video.setAttribute('loop', '');
  video.setAttribute('playsinline', '');
  video.setAttribute('aria-hidden', 'true');
  video.tabIndex = -1;

  function addSource(src, type) {
    if (!src) return;
    var s = document.createElement('source');
    s.src = src;
    s.type = type;
    video.appendChild(s);
  }
  addSource(webm, 'video/webm');
  addSource(mp4, 'video/mp4');

  // Показуємо відео лише коли перший кадр реально готовий -- інакше замість
  // постера мигне порожній прямокутник.
  video.addEventListener('playing', function () {
    video.classList.add('is-ready');
  });
  video.addEventListener('error', function () {
    if (video.parentNode) video.parentNode.removeChild(video);
  });

  box.appendChild(video);

  var p = video.play();
  if (p && typeof p.catch === 'function') {
    p.catch(function () {
      // Автоплей заблоковано політикою браузера -- лишаємо постер.
      if (video.parentNode) video.parentNode.removeChild(video);
    });
  }
})();
