/**
 * Шпилька бокової панелі адмінки і «підглядання» після переходу.
 *
 * У спокої панель -- смуга іконок і розкривається наведенням; це робить
 * CSS сам (:hover / :focus-within), сюди воно НЕ заходить. Скрипт
 * відповідає за дві речі: чи тримати панель розкритою постійно (шпилька) і
 * чи показати її розкритою на свіжій сторінці (peek, див. нижче).
 *
 * Стан шпильки живе в кукі, а не в localStorage. localStorage видно лише
 * після старту скрипта, тобто вже після першого малювання -- закріплена
 * панель встигала б блимнути смугою на кожному переході. Кукі ж читає
 * сервер і віддає готовий клас у розмітці (admin/partials/_sidebar.html).
 */
(function () {
  'use strict';

  var COOKIE = 'admin_sidebar_pinned';
  var YEAR = 60 * 60 * 24 * 365;

  /* Та сама межа, що й смуга в admin.css, плюс справжній курсор: на
     сенсорному екрані :hover після дотику «залипає», а pointermove, що
     знімає peek, може так і не прийти -- панель лишилась би розкритою. */
  var DESKTOP_QUERY = '(min-width: 1025px) and (hover: hover)';
  var PEEK_KEY = 'admin-sidebar-peek';
  /* Скільки позначка чинна: вона про сторінку, що відкрилась одразу після
     кліку, а не про адмінку, в яку повернулись за хвилину. */
  var PEEK_TTL_MS = 10000;

  var sidebar = document.getElementById('admin-sidebar');
  if (!sidebar) return;
  var desktop = window.matchMedia(DESKTOP_QUERY);

  /* Peek -- «розкрита під курсором» на НОВІЙ сторінці. Людина клацнула
     пункт розкритої панелі, курсор і далі над нею, але свіжа сторінка
     :hover ще не знає: панель малювалась смугою, щоб за мить розкритись
     знову. Тут, а не на DOMContentLoaded, -- щоб устигнути якомога раніше.
     Клас ставиться без анімації (--instant на два кадри), перший рух миші
     його знімає -- далі все вирішує :hover.

     sessionStorage, а не кукі: кукі, змінена в момент кліку, ламала б
     сторінкам із no-store повернення назад/вперед з кешу. */
  var peek = false;
  try {
    var left = Number(sessionStorage.getItem(PEEK_KEY));
    peek = left > 0 && Date.now() - left < PEEK_TTL_MS;
    sessionStorage.removeItem(PEEK_KEY);
  } catch (e) {
    // Без сховища панель просто стартує смугою.
  }

  if (peek && desktop.matches && !sidebar.classList.contains('admin-sidebar--pinned')) {
    sidebar.classList.add('admin-sidebar--instant', 'admin-sidebar--peek');
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        sidebar.classList.remove('admin-sidebar--instant');
      });
    });
    document.addEventListener('pointermove', function () {
      sidebar.classList.remove('admin-sidebar--peek');
    }, { once: true });
  }

  /* Позначка ставиться в момент кліку, а не на pagehide: до pagehide Chrome
     уже знімає :hover зі старого документа. Клік із модифікатором відкриває
     нову вкладку -- ця сторінка нікуди не йде. */
  sidebar.addEventListener('click', function (e) {
    if (!e.target.closest('a[href]') || e.button !== 0
        || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) {
      return;
    }
    var open = desktop.matches
      && !sidebar.classList.contains('admin-sidebar--pinned')
      && sidebar.matches(':hover');
    try {
      if (open) sessionStorage.setItem(PEEK_KEY, String(Date.now()));
    } catch (err) {
      // Нема куди зберегти -- наступна сторінка почне зі смуги.
    }
  });

  var pin = document.getElementById('admin-sidebar-pin');
  if (!pin) return;

  pin.addEventListener('click', function (e) {
    var pinned = !sidebar.classList.contains('admin-sidebar--pinned');
    sidebar.classList.toggle('admin-sidebar--pinned', pinned);
    // Peek -- лише до першої дії; відкріплена панель далі слухає :hover.
    sidebar.classList.remove('admin-sidebar--peek');

    var label = pinned
      ? 'Відкріпити панель навігації'
      : 'Закріпити панель навігації';
    pin.setAttribute('aria-pressed', pinned ? 'true' : 'false');
    pin.setAttribute('aria-label', label);
    pin.setAttribute('title', label);

    document.cookie = COOKIE + '=' + (pinned ? '1' : '0')
      + '; path=/; max-age=' + YEAR + '; SameSite=Lax';

    /* Фокус після кліку мишею лишився б на шпильці, і :focus-within тримав
       би відкріплену панель розкритою ПОВЕРХ вмісту, коли курсор уже пішов:
       клік у таблицю влучав би в меню. У клавіатурного натискання
       e.detail === 0, і фокус у нього забирати не можна. */
    if (e.detail > 0) pin.blur();
  });
})();
