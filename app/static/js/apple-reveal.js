/* apple-reveal.js -- IntersectionObserver scroll reveal (Apple concept v2) */
/* Fallback for browsers without CSS animation-timeline: view() support */
(function () {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var els = document.querySelectorAll('.apple-reveal');
  if (!els.length) return;

  var obs = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        e.target.classList.add('visible');
        obs.unobserve(e.target);
      }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

  els.forEach(function (el) { obs.observe(el); });
})();
