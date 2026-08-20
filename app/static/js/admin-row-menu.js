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
    var right = Math.max(8, window.innerWidth - r.right);
    // ...але не даємо вилізти за лівий край. Вузьке меню-список поруч із
    // кнопкою в правій колонці вміщалось завжди; широка панель із формою
    // (причина відмови) біля кнопки зліва опинялась за екраном -- виглядало
    // так, ніби меню взагалі не відкривається.
    var width = panel.offsetWidth;
    if (window.innerWidth - right - width < 8) {
      right = Math.max(8, window.innerWidth - width - 8);
    }
    panel.style.right = right + 'px';
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

  function openMenu() {
    return document.querySelector('details.admin-actions-menu[open]');
  }

  function focusInsideMenu() {
    var el = document.activeElement;
    return !!(el && el.closest && el.closest('.admin-actions-menu'));
  }

  /* Клавіатура на телефоні -- це теж resize. Поки курсор усередині меню,
     переставляємо панель, а не закриваємо: інакше меню зникало рівно тоді,
     коли людина почала друкувати. */
  window.addEventListener('resize', function () {
    var open = openMenu();
    if (open && focusInsideMenu()) {
      position(open);
      return;
    }
    closeAll(null);
  });

  /* Слухаємо у фазі захоплення, бо scroll не спливає -- інакше не впіймати
     прокрутку .admin-table-wrap. Але так само сюди прилітає scroll ВІД ПОЛЯ
     ВВЕДЕННЯ: текст, довший за ширину поля, прокручує його вміст. Через це
     меню закривалось на першому ж зайвому символі причини відмови. Тому
     прокрутку зсередини меню пропускаємо. */
  document.addEventListener('scroll', function (e) {
    var t = e.target;
    if (t && t.closest && t.closest('.admin-actions-menu')) return;
    closeAll(null);
  }, true);
})();
