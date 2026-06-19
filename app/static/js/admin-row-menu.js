/* admin-row-menu.js -- випадаючі меню дій у рядках таблиці.

   Працює з <details class="admin-actions-menu">. Панель .admin-actions-menu__items
   позиціонується fixed (через JS), щоб не обрізалась контейнером
   .admin-table-wrap { overflow: auto }. Відкриває одне меню за раз, закриває
   при кліку поза, скролі та resize. CSS-only fallback також працює. */
(function () {
  'use strict';

  function closeAll(except) {
    document.querySelectorAll('details.admin-actions-menu[open]').forEach(function (d) {
      if (d !== except) d.removeAttribute('open');
    });
  }

  function position(details) {
    var summary = details.querySelector('summary');
    var panel = details.querySelector('.admin-actions-menu__items');
    if (!summary || !panel) return;
    var r = summary.getBoundingClientRect();
    panel.style.left = 'auto';
    // Прив'язуємо праву межу панелі до правої межі кнопки.
    panel.style.right = Math.max(8, window.innerWidth - r.right) + 'px';
    var ph = panel.offsetHeight;
    if (r.bottom + 4 + ph > window.innerHeight && r.top - 4 - ph > 0) {
      // Не влазить донизу -- відкриваємо вгору.
      panel.style.top = 'auto';
      panel.style.bottom = (window.innerHeight - r.top + 4) + 'px';
    } else {
      panel.style.bottom = 'auto';
      panel.style.top = (r.bottom + 4) + 'px';
    }
  }

  // toggle не спливає -- слухаємо у фазі захоплення.
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (!(d.tagName === 'DETAILS' && d.classList.contains('admin-actions-menu'))) return;
    if (d.open) {
      closeAll(d);
      position(d);
    }
  }, true);

  document.addEventListener('click', function (e) {
    if (!e.target.closest('.admin-actions-menu')) closeAll(null);
  });

  window.addEventListener('resize', function () { closeAll(null); });
  document.addEventListener('scroll', function () { closeAll(null); }, true);
})();
