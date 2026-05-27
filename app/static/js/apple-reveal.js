/* apple-reveal.js -- IntersectionObserver scroll reveal (Apple concept v2) */
/* Fallback for browsers without CSS animation-timeline: view() support */
(function () {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var els = document.querySelectorAll('.apple-reveal');
  if (!els.length) return;

  // Stagger: елементи, що входять у viewport в одному «пакеті»
  // IntersectionObserver-callback-у, з'являються каскадом (0, 70, 140мс...).
  // Затримку обмежуємо, щоб довгі списки не тягнулись надто довго.
  var STAGGER_MS = 70;
  var STAGGER_MAX = 6; // максимум кроків затримки

  var obs = new IntersectionObserver(function (entries) {
    var batch = entries.filter(function (e) { return e.isIntersecting; });
    batch.forEach(function (e, i) {
      var delay = Math.min(i, STAGGER_MAX) * STAGGER_MS;
      e.target.style.transitionDelay = delay + 'ms';
      e.target.classList.add('visible');
      obs.unobserve(e.target);
      // прибираємо delay після появи, щоб hover-transition не лагали
      window.setTimeout(function () {
        e.target.style.transitionDelay = '';
      }, delay + 800);
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

  els.forEach(function (el) { obs.observe(el); });
})();
