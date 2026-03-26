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

  /* Scramble text -- ефект вертикального циферблату */
  var DIGITS = '0123456789';

  function scrambleText(el) {
    var finalText = el.getAttribute('data-text');
    if (!finalText) return;
    var chars = finalText.split('');

    /* Побудувати DOM: кожен символ -- окремий слот */
    el.textContent = '';
    var slots = [];
    chars.forEach(function (ch, i) {
      var wrap = document.createElement('span');
      wrap.className = 'scramble-text__char';

      /* Стовпець: 8 випадкових цифр + фінальна літера */
      var count = 8 + Math.floor(Math.random() * 4);
      var sequence = '';
      for (var j = 0; j < count; j++) {
        sequence += DIGITS[Math.floor(Math.random() * DIGITS.length)] + '\n';
      }
      sequence += ch;

      var inner = document.createElement('span');
      inner.className = 'scramble-text__inner';
      inner.style.whiteSpace = 'pre';
      inner.textContent = sequence;

      /* Стартова позиція -- зверху (перша цифра) */
      inner.style.transform = 'translateY(0)';
      inner.style.transition = 'none';

      wrap.appendChild(inner);
      el.appendChild(wrap);

      slots.push({
        inner: inner,
        lines: count + 1,
        delay: i * 120
      });
    });

    /* Запуск анімації -- прокрутка до фінальної літери */
    requestAnimationFrame(function () {
      slots.forEach(function (slot) {
        setTimeout(function () {
          var offset = -(slot.lines - 1) * 100 / slot.lines;
          slot.inner.style.transition =
            'transform ' + (0.8 + slot.lines * 0.06) + 's cubic-bezier(0.22, 1, 0.36, 1)';
          slot.inner.style.transform = 'translateY(' + offset + '%)';
        }, slot.delay);
      });
    });
  }

  /* Спостерігач для scramble */
  var scrambleEls = document.querySelectorAll('.scramble-text');
  if (scrambleEls.length) {
    var scrambleObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          scrambleText(entry.target);
          scrambleObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });

    scrambleEls.forEach(function (el) { scrambleObserver.observe(el); });
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
