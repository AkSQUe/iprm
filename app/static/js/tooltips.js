/* tooltips.js — спливаючі підказки на [data-tooltip].

   Тригер (зазвичай «i»-іконка) показує bubble з текстом підказки
   на hover / focus / click(tap). Позиціонується над тригером, при
   браку місця зверху — знизу. ARIA-доступний.

   Vanilla JS, без залежностей. Single Responsibility: лише tooltips. */
(function () {
  'use strict';

  function initTooltips() {
    var triggers = document.querySelectorAll('[data-tooltip]');
    triggers.forEach(function (trigger) {
      if (trigger.__iprmTooltipBound) return;
      trigger.__iprmTooltipBound = true;

      trigger.setAttribute('tabindex', trigger.getAttribute('tabindex') || '0');
      trigger.setAttribute('role', 'button');
      trigger.setAttribute('aria-label', 'Підказка: ' + trigger.getAttribute('data-tooltip'));

      var bubble = null;

      function show() {
        if (bubble) return;
        bubble = document.createElement('span');
        bubble.className = 'iprm-tooltip-bubble';
        bubble.textContent = trigger.getAttribute('data-tooltip');
        document.body.appendChild(bubble);
        var r = trigger.getBoundingClientRect();
        var top = window.scrollY + r.top - bubble.offsetHeight - 10;
        var left = window.scrollX + r.left + r.width / 2 - bubble.offsetWidth / 2;
        left = Math.max(8, left);
        if (top < window.scrollY + 4) {
          top = window.scrollY + r.bottom + 10;
          bubble.classList.add('iprm-tooltip-bubble--below');
        }
        bubble.style.top = top + 'px';
        bubble.style.left = left + 'px';
        requestAnimationFrame(function () { if (bubble) bubble.classList.add('is-visible'); });
      }
      function hide() {
        if (!bubble) return;
        var b = bubble;
        bubble = null;
        b.classList.remove('is-visible');
        setTimeout(function () { if (b.parentNode) b.parentNode.removeChild(b); }, 200);
      }

      trigger.addEventListener('mouseenter', show);
      trigger.addEventListener('mouseleave', hide);
      trigger.addEventListener('focus', show);
      trigger.addEventListener('blur', hide);
      trigger.addEventListener('click', function (e) {
        e.preventDefault();
        if (bubble) hide(); else show();
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTooltips);
  } else {
    initTooltips();
  }
})();
