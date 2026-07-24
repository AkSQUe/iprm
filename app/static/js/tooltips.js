/* tooltips.js — спливаючі підказки на [data-tooltip].

   Тригер (зазвичай «i»-іконка) показує bubble з текстом підказки
   на hover / focus / click(tap). Позиціонується над тригером, при
   браку місця зверху — знизу. ARIA-доступний.

   Vanilla JS, без залежностей. Single Responsibility: лише tooltips. */
(function () {
  'use strict';

  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  function initTooltips() {
    var triggers = document.querySelectorAll('[data-tooltip]');
    triggers.forEach(function (trigger) {
      if (trigger.__iprmTooltipBound) return;
      trigger.__iprmTooltipBound = true;

      trigger.setAttribute('tabindex', trigger.getAttribute('tabindex') || '0');
      trigger.setAttribute('role', 'button');
      trigger.setAttribute('aria-label', t('Підказка: {text}', { text: trigger.getAttribute('data-tooltip') }));

      var bubble = null;

      function show() {
        if (bubble) return;
        bubble = document.createElement('span');
        bubble.className = 'iprm-tooltip-bubble';
        bubble.textContent = trigger.getAttribute('data-tooltip');
        document.body.appendChild(bubble);
        // position: fixed => координати у системі viewport (без scrollX/Y).
        // Fixed-елемент не контрибутить у scroll-розмір документа, тож
        // сторінка не «розтягується» й не з'являється порожнеча під footer.
        var r = trigger.getBoundingClientRect();
        var bw = bubble.offsetWidth;
        var bh = bubble.offsetHeight;
        var vw = document.documentElement.clientWidth;
        var top = r.top - bh - 10;
        var left = r.left + r.width / 2 - bw / 2;
        // тримаємо в межах вьюпорта по горизонталі
        left = Math.max(8, Math.min(left, vw - bw - 8));
        // якщо зверху не влазить — показуємо знизу
        if (top < 4) {
          top = r.bottom + 10;
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
