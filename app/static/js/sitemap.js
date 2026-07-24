/* sitemap.js -- Visual sitemap toggle interactivity */
(function () {
  'use strict';

  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  document.addEventListener('click', function (e) {
    var toggle = e.target.closest('[data-sitemap-toggle]');
    if (toggle) {
      var expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!expanded));
      return;
    }

    var more = e.target.closest('[data-sitemap-expand]');
    if (more) {
      var expanded = more.getAttribute('aria-expanded') === 'true';
      more.setAttribute('aria-expanded', String(!expanded));
      var children = more.nextElementSibling;
      if (children && children.classList.contains('sitemap-section__children')) {
        children.hidden = expanded;
      }
      var label = more.querySelector('span:first-child');
      if (label) {
        var count = children ? children.children.length : 0;
        label.textContent = expanded
          ? t('Показати ще ({count})', { count: count })
          : t('Згорнути');
      }
    }
  });
})();
