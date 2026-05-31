/* admin-confirm.js -- admin-only UI helpers.

   Підтвердження дій (data-confirm) обробляє глобальний confirm-action.js
   (стилізована модалка сайту), що вантажиться у base.html. Тут нативний
   confirm() НЕ використовуємо -- інакше на адмінці спрацьовували б обидва
   (нативне вікно + модалка). Лишаємо тільки авто-сабміт file-input. */
(function () {
  /* Auto-submit file input (import). Програмний submit() не тригерить
     submit-event, тож не конфліктує з confirm-action.js. */
  document.addEventListener('change', function (e) {
    var el = e.target;
    if (el.classList.contains('admin-file-input')) {
      el.form.submit();
    }
  });
})();
