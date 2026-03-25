/* page-index.js -- скрипти тільки для головної сторінки */
(function () {
  /* Scroll reveal (з більшим порогом для головної) */
  var revealEls = document.querySelectorAll('.apple-reveal');
  if (revealEls.length) {
    var revealObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          revealObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15, rootMargin: '0px 0px -60px 0px' });

    revealEls.forEach(function (el) { revealObserver.observe(el); });
  }

  /* Counter animation for stats */
  function animateCounter(el, target, suffix) {
    var duration = 2000;
    var start = performance.now();

    function update(now) {
      var elapsed = now - start;
      var progress = Math.min(elapsed / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      var current = Math.floor(target * eased);
      el.textContent = current + suffix;
      if (progress < 1) requestAnimationFrame(update);
    }

    requestAnimationFrame(update);
  }

  var statsRow = document.getElementById('stats-row');
  if (statsRow) {
    var statsObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var items = entry.target.querySelectorAll('.apple-stat h3');
          items.forEach(function (item) {
            var target = parseInt(item.getAttribute('data-target'));
            var suffix = item.getAttribute('data-suffix') || '';
            if (target) animateCounter(item, target, suffix);
          });
          statsObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.3 });

    statsObserver.observe(statsRow);
  }

  /* Smooth scroll for anchor links */
  document.querySelectorAll('.page-index a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var target = document.querySelector(this.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });
})();
