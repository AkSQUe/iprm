/* reading-progress.js — індикатор прогресу читання + кнопка «нагору».

   Авто-активується на довгих сторінках з класом .legal-page
   (privacy, offer, refund, disclaimer, cookies, bpr-documents).

   Vanilla JS. Single Responsibility. */
(function () {
  'use strict';

  function init() {
    if (!document.querySelector('.legal-page')) return;

    var bar = document.createElement('div');
    bar.className = 'iprm-reading-progress';
    bar.setAttribute('aria-hidden', 'true');
    bar.innerHTML = '<span></span>';
    document.body.appendChild(bar);
    var fill = bar.firstChild;

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'iprm-to-top';
    btn.setAttribute('aria-label', 'Нагору');
    btn.innerHTML = '<span aria-hidden="true">↑</span>';
    document.body.appendChild(btn);

    btn.addEventListener('click', function () {
      var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
    });

    var ticking = false;
    function onScroll() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        var h = document.documentElement;
        var scrollable = h.scrollHeight - h.clientHeight;
        var pct = scrollable > 0 ? (h.scrollTop / scrollable) * 100 : 0;
        fill.style.width = pct.toFixed(1) + '%';
        btn.classList.toggle('is-visible', h.scrollTop > 400);
        ticking = false;
      });
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    onScroll();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
