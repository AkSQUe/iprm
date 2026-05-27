/* faq-accordion.js — плавне розгортання FAQ (<details>) + single-open.

   Працює з розміткою:
     <div class="iprm-faq">
       <details class="iprm-faq__item">
         <summary class="iprm-faq__question">...</summary>
         <div class="iprm-faq__answer">...</div>
       </details>
     </div>

   Анімує height відповіді; за замовчуванням закриває інші відкриті у
   тому ж .iprm-faq (accordion). Vanilla JS. Single Responsibility. */
(function () {
  'use strict';

  var DURATION = 280;

  function closeWithAnim(details, content) {
    var h = content.offsetHeight;
    content.style.height = h + 'px';
    content.style.overflow = 'hidden';
    requestAnimationFrame(function () {
      content.style.transition = 'height ' + DURATION + 'ms ease';
      content.style.height = '0px';
    });
    window.setTimeout(function () {
      details.open = false;
      content.style.transition = '';
      content.style.height = '';
      content.style.overflow = '';
    }, DURATION);
  }

  function openWithAnim(details, content) {
    details.open = true;
    var h = content.scrollHeight;
    content.style.overflow = 'hidden';
    content.style.height = '0px';
    requestAnimationFrame(function () {
      content.style.transition = 'height ' + DURATION + 'ms ease';
      content.style.height = h + 'px';
    });
    window.setTimeout(function () {
      content.style.transition = '';
      content.style.height = '';
      content.style.overflow = '';
    }, DURATION);
  }

  function init() {
    var faqs = document.querySelectorAll('.iprm-faq');
    faqs.forEach(function (faq) {
      var items = faq.querySelectorAll('.iprm-faq__item');
      items.forEach(function (details) {
        var summary = details.querySelector('.iprm-faq__question');
        var content = details.querySelector('.iprm-faq__answer');
        if (!summary || !content) return;

        summary.addEventListener('click', function (e) {
          e.preventDefault();
          if (details.open) {
            closeWithAnim(details, content);
          } else {
            // single-open: закрити інші відкриті у цьому ж faq
            items.forEach(function (other) {
              if (other !== details && other.open) {
                var oc = other.querySelector('.iprm-faq__answer');
                if (oc) closeWithAnim(other, oc);
              }
            });
            openWithAnim(details, content);
          }
        });
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
