/**
 * Шпилька бокової панелі адмінки.
 *
 * У спокої панель -- смуга іконок і розкривається наведенням; це робить
 * CSS сам (:hover / :focus-within), сюди воно НЕ заходить. Скрипт
 * відповідає рівно за одне: чи тримати панель розкритою постійно.
 *
 * Стан живе в кукі, а не в localStorage. localStorage видно лише після
 * старту скрипта, тобто вже після першого малювання -- закріплена панель
 * встигала б блимнути смугою на кожному переході. Кукі ж читає сервер і
 * віддає готовий клас у розмітці (admin/partials/_sidebar.html).
 */
(function () {
  'use strict';

  var COOKIE = 'admin_sidebar_pinned';
  var YEAR = 60 * 60 * 24 * 365;

  document.addEventListener('DOMContentLoaded', function () {
    var sidebar = document.getElementById('admin-sidebar');
    var pin = document.getElementById('admin-sidebar-pin');
    if (!sidebar || !pin) return;

    pin.addEventListener('click', function () {
      var pinned = !sidebar.classList.contains('admin-sidebar--pinned');
      sidebar.classList.toggle('admin-sidebar--pinned', pinned);

      var label = pinned
        ? 'Відкріпити панель навігації'
        : 'Закріпити панель навігації';
      pin.setAttribute('aria-pressed', pinned ? 'true' : 'false');
      pin.setAttribute('aria-label', label);
      pin.setAttribute('title', label);

      document.cookie = COOKIE + '=' + (pinned ? '1' : '0')
        + '; path=/; max-age=' + YEAR + '; SameSite=Lax';
    });
  });
})();
