/* counters.js -- анімація числових лічильників на Головній.

   Елемент [data-counter="N"] (опц. data-suffix) анімується від 0 до N, коли
   потрапляє у в'юпорт. Поважає prefers-reduced-motion. Vanilla JS. */
(function () {
  'use strict';

  var els = document.querySelectorAll('[data-counter]');
  if (!els.length) return;

  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function setFinal(el) {
    var target = parseInt(el.getAttribute('data-counter'), 10) || 0;
    el.textContent = target + (el.getAttribute('data-suffix') || '');
  }

  function animate(el) {
    var target = parseInt(el.getAttribute('data-counter'), 10) || 0;
    var suffix = el.getAttribute('data-suffix') || '';
    if (reduce || target <= 0) { el.textContent = target + suffix; return; }
    var start = null;
    var dur = 1000;
    function step(ts) {
      if (start === null) start = ts;
      var p = Math.min((ts - start) / dur, 1);
      el.textContent = Math.round(p * target) + suffix;
      if (p < 1) window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  }

  if (!('IntersectionObserver' in window)) {
    els.forEach(setFinal);
    return;
  }

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        animate(e.target);
        io.unobserve(e.target);
      }
    });
  }, { threshold: 0.4 });

  els.forEach(function (el) { io.observe(el); });
})();
