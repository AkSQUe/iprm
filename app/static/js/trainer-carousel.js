/* trainer-carousel.js -- нескінченний слайдер тренерів на Головній.
 *
 * Стрілки prev/next + статус "N із total", scroll-snap-в'юпорт, автоперемикання
 * (пауза на hover/focus/pointer, лише коли секція у в'юпорті). Поважає
 * prefers-reduced-motion. Нескінченний цикл -- через клони оригінальних
 * слайдів (prepend + append) і "стрибок" після плавного скролу. Vanilla JS. */
(function () {
  'use strict';

  var carousel = document.querySelector('[data-trainer-carousel]');
  if (!carousel) return;

  var viewport = carousel.querySelector('.trainer-carousel__viewport');
  var track = carousel.querySelector('.trainer-carousel__track');
  var prevBtn = carousel.querySelector('[data-carousel-prev]');
  var nextBtn = carousel.querySelector('[data-carousel-next]');
  var posOut = carousel.querySelector('[data-carousel-position]');
  var totalOut = carousel.querySelector('[data-carousel-total]');
  if (!viewport || !track) return;

  var originalSlides = Array.prototype.slice.call(track.children);
  if (originalSlides.length < 2) return;  // слайдер не потрібен

  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  var copyWidth = 0;
  var scrollTimer, autoplayTimer, progTimer;
  var isHovering = false, hasFocus = false, isVisible = false, isProgrammatic = false;
  var currentIndex = 0;

  function cloneSlides() {
    var frag = document.createDocumentFragment();
    originalSlides.forEach(function (slide) {
      var clone = slide.cloneNode(true);
      clone.classList.add('trainer-slide--clone');
      clone.setAttribute('aria-hidden', 'true');
      clone.querySelectorAll('a, button, [tabindex]').forEach(function (el) {
        el.setAttribute('tabindex', '-1');
      });
      frag.appendChild(clone);
    });
    return frag;
  }

  track.prepend(cloneSlides());
  track.appendChild(cloneSlides());
  if (totalOut) totalOut.textContent = String(originalSlides.length);

  function getStep() {
    var gap = parseFloat(getComputedStyle(track).gap) || 0;
    return originalSlides[0].getBoundingClientRect().width + gap;
  }

  function indexFromScroll() {
    var step = getStep();
    if (!step) return 0;
    var raw = Math.round((viewport.scrollLeft - copyWidth) / step);
    var n = originalSlides.length;
    return ((raw % n) + n) % n;
  }

  function updatePosition() {
    if (posOut) posOut.textContent = String(currentIndex + 1);
  }

  function jumpTo(left) {
    viewport.classList.add('is-jumping');
    viewport.scrollLeft = left;
    requestAnimationFrame(function () { viewport.classList.remove('is-jumping'); });
  }

  function syncFromScroll() {
    currentIndex = indexFromScroll();
    jumpTo(copyWidth + currentIndex * getStep());
    updatePosition();
  }

  function stopAutoplay() { window.clearInterval(autoplayTimer); }

  function startAutoplay() {
    stopAutoplay();
    if (reduced.matches || isHovering || hasFocus || !isVisible) return;
    autoplayTimer = window.setInterval(function () { move(1); }, 4200);
  }

  function move(direction, manual) {
    var n = originalSlides.length;
    var last = n - 1;
    var step = getStep();
    var prevIndex = currentIndex;
    currentIndex = (currentIndex + direction + n) % n;

    var target = copyWidth + currentIndex * step;
    if (direction > 0 && prevIndex === last) {
      target = copyWidth * 2;
    } else if (direction < 0 && prevIndex === 0) {
      target = copyWidth - step;
    }

    isProgrammatic = true;
    updatePosition();
    viewport.scrollTo({ left: target, behavior: reduced.matches ? 'auto' : 'smooth' });

    window.clearTimeout(progTimer);
    progTimer = window.setTimeout(function () {
      jumpTo(copyWidth + currentIndex * step);
      isProgrammatic = false;
    }, reduced.matches ? 0 : 520);

    if (manual) startAutoplay();
  }

  function resetLayout() {
    copyWidth = getStep() * originalSlides.length;
    jumpTo(copyWidth + currentIndex * getStep());
    updatePosition();
  }

  viewport.addEventListener('scroll', function () {
    if (isProgrammatic) return;
    window.clearTimeout(scrollTimer);
    scrollTimer = window.setTimeout(syncFromScroll, 160);
  }, { passive: true });

  if (prevBtn) prevBtn.addEventListener('click', function () { move(-1, true); });
  if (nextBtn) nextBtn.addEventListener('click', function () { move(1, true); });

  viewport.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft') { e.preventDefault(); move(-1, true); }
    if (e.key === 'ArrowRight') { e.preventDefault(); move(1, true); }
  });

  carousel.addEventListener('mouseenter', function () { isHovering = true; stopAutoplay(); });
  carousel.addEventListener('mouseleave', function () { isHovering = false; startAutoplay(); });
  carousel.addEventListener('focusin', function () { hasFocus = true; stopAutoplay(); });
  carousel.addEventListener('focusout', function () {
    hasFocus = carousel.contains(document.activeElement);
    startAutoplay();
  });
  viewport.addEventListener('pointerdown', function () {
    isProgrammatic = false;
    window.clearTimeout(progTimer);
    stopAutoplay();
  });
  viewport.addEventListener('pointerup', startAutoplay);

  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      isVisible = entries[0].isIntersecting;
      startAutoplay();
    }, { threshold: 0.35 });
    io.observe(carousel);
  } else {
    isVisible = true;
  }

  reduced.addEventListener('change', startAutoplay);
  window.addEventListener('resize', function () { window.requestAnimationFrame(resetLayout); });
  window.addEventListener('load', resetLayout, { once: true });
  resetLayout();
  startAutoplay();
})();
