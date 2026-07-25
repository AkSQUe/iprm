/* home-hero-video.js -- фонове відео у hero Головної (progressive enhancement).

   Розмітка віддає лише постер-зображення; сам <video> створюється тут і лише
   тоді, коли це доречно: широкий екран, вказівник миші, немає
   prefers-reduced-motion, немає економії трафіку та повільного каналу. Так
   мобільні й вузькі канали не тягнуть ~1.2 МБ.

   Далі відео живе за станом сторінки: грає, поки hero у в'юпорті, і стає на
   паузу, щойно його прокрутили (Головна ~12 000px -- інакше декодер працює
   майже весь візит намарно). Vanilla JS. */
(function () {
  'use strict';

  var box = document.querySelector('[data-hero-video]');
  if (!box) return;

  var mq = window.matchMedia;
  if (!mq) return;

  var motionMq = mq('(prefers-reduced-motion: reduce)');
  if (motionMq.matches) return;
  if (!mq('(min-width: 768px)').matches) return;
  // pointer: fine -- відсікає тач-первинні пристрої, але лишає сенсорні
  // ноутбуки, де основний вказівник усе одно миша.
  if (!mq('(pointer: fine)').matches) return;

  var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (conn) {
    if (conn.saveData) return;
    // 1.2 МБ фонового відео на 2G/3G -- це секунди чужого трафіку заради декору.
    if (/(^|-)[23]g$/.test(conn.effectiveType || '')) return;
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

  var sources = 0;
  var failed = 0;

  function addSource(src, type) {
    if (!src) return;
    var s = document.createElement('source');
    s.src = src;
    s.type = type;
    // Коли джерела задані через <source>, подія error летить саме в них, а не
    // в media-елемент -- слухати треба тут. Знімаємо відео лише коли впали ВСІ.
    s.addEventListener('error', function () {
      failed += 1;
      if (failed >= sources) remove();
    });
    video.appendChild(s);
    sources += 1;
  }
  addSource(webm, 'video/webm');
  addSource(mp4, 'video/mp4');

  var wanted = true;      // чи хочемо програвати за поточного стану сторінки
  var retryArmed = false;

  function remove() {
    wanted = false;
    disarmRetry();
    if (io) io.disconnect();
    if (video.parentNode) video.parentNode.removeChild(video);
    box.classList.remove('is-video-ready');
  }

  function onRetry() {
    disarmRetry();
    tryPlay();
  }

  function armRetry() {
    if (retryArmed) return;
    retryArmed = true;
    document.addEventListener('visibilitychange', onRetry);
    document.addEventListener('pointerdown', onRetry, true);
    document.addEventListener('keydown', onRetry, true);
  }

  function disarmRetry() {
    if (!retryArmed) return;
    retryArmed = false;
    document.removeEventListener('visibilitychange', onRetry);
    document.removeEventListener('pointerdown', onRetry, true);
    document.removeEventListener('keydown', onRetry, true);
  }

  function tryPlay() {
    if (!wanted || !video.parentNode) return;
    var p = video.play();
    if (p && typeof p.catch === 'function') {
      p.catch(function () {
        // Автоплей заблокований політикою браузера (напр. режим енергозбереження
        // у Safari). Постер лишається на місці; пробуємо ще раз, коли вкладка
        // стане видимою або користувач хоч якось взаємодіє зі сторінкою.
        armRetry();
      });
    }
  }

  // Показуємо відео лише коли перший кадр реально готовий -- інакше замість
  // постера мигне порожній прямокутник.
  video.addEventListener('playing', function () {
    video.classList.add('is-ready');
    box.classList.add('is-video-ready');
  });

  box.appendChild(video);

  var io = null;
  if ('IntersectionObserver' in window) {
    io = new IntersectionObserver(function (entries) {
      var visible = entries[entries.length - 1].isIntersecting;
      wanted = visible;
      if (visible) {
        tryPlay();
      } else if (!video.paused) {
        video.pause();
      }
    }, { threshold: 0 });
    io.observe(box);
  }

  tryPlay();

  // Користувач може увімкнути "менше руху" вже з відкритою сторінкою.
  if (typeof motionMq.addEventListener === 'function') {
    motionMq.addEventListener('change', function (e) {
      if (e.matches) remove();
    });
  }
})();
