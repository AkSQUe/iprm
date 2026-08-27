/* Автоматична відправка форми при зміні поля.
 *
 * Замінює inline `onchange="this.form.submit()"`, який стояв у восьми місцях
 * адмінки (вибір xlsx-файлу, фільтр за станом). Inline-обробники заборонені
 * глобальною політикою проєкту й до того ж вимикаються будь-якою суворою CSP:
 * форма мовчки переставала відправлятись, а користувач бачив лише те, що
 * "кнопка не працює".
 *
 * Розмітка: `data-autosubmit` на самому полі (input[type=file], select).
 * Делегування на document -- поля, додані динамічно, працюють без переприв'язки.
 */
(function () {
  'use strict';

  document.addEventListener('change', function (event) {
    var field = event.target;
    if (!field || !field.hasAttribute || !field.hasAttribute('data-autosubmit')) {
      return;
    }
    var form = field.form || field.closest('form');
    if (!form) {
      return;
    }
    // requestSubmit -- щоб спрацювала валідація й подія submit (її слухає
    // admin-confirm.js). form.submit() обидві мовчки пропускає.
    if (typeof form.requestSubmit === 'function') {
      form.requestSubmit();
    } else {
      form.submit();
    }
  });
})();
