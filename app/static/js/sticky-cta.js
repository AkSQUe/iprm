/* sticky-cta.js — липка нижня CTA-панель (mobile) на сторінці курсу.

   Показується коли hero-кнопки прокручені за межі екрана, ховається
   коли вони знову видимі. Видимість панелі керується атрибутом [hidden];
   фактичний показ — лише на mobile (CSS media query).

   Vanilla JS + IntersectionObserver. Single Responsibility. */
(function () {
  'use strict';

  var bar = document.querySelector('[data-sticky-cta]');
  if (!bar) return;

  var anchor = document.querySelector('[data-sticky-cta-anchor]')
    || document.querySelector('.iprm-hero__actions--detail')
    || document.querySelector('.iprm-hero');
  if (!anchor) return;

  if (!('IntersectionObserver' in window)) {
    // Без підтримки — показуємо панель завжди (на mobile через CSS).
    bar.hidden = false;
    return;
  }

  var obs = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      // hero-кнопки видно → ховаємо панель; проскролили → показуємо
      bar.hidden = e.isIntersecting;
    });
  }, { threshold: 0 });

  obs.observe(anchor);
})();
