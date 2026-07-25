/* form-single-submit.js -- захист від подвійного сабміту.
   Форма з атрибутом data-single-submit після першого submit блокує кнопку
   та додає data-submitting, щоб CSS міг показати loading-стан.

   Опціонально:
     data-submitting-label="Створюємо копію…"  -- напис замість "Надсилаємо…"

   Не вішати на форми, де сабміт-кнопки розрізняються за name/value
   (як "перевірити" і "виконати" в одній формі): вимкнена кнопка не
   потрапляє до даних форми, і сервер не побачить, яку саме натиснули. */
(function () {
  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  /* Делегування на document: форми з data-confirm пересилаються програмно
     (confirm-action.js), а частина сторінок домальовує форми після
     завантаження -- перелік на старті швидко застарів би. */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.matches || !form.matches('form[data-single-submit]')) return;

    /* Сабміт уже скасований кимось іншим -- діалогом підтвердження або
       валідацією форми. Блокувати кнопку тут не можна: якщо користувач
       натисне "Скасувати" або не виправить поле, форма лишиться мертвою
       до перезавантаження сторінки. */
    if (e.defaultPrevented) return;

    if (form.dataset.submitting === 'true') return;
    form.dataset.submitting = 'true';
    var label = form.dataset.submittingLabel || t('Надсилаємо…');
    var buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
    buttons.forEach(function (btn) {
      btn.disabled = true;
      if (btn.dataset.defaultLabel === undefined && btn.textContent) {
        btn.dataset.defaultLabel = btn.textContent;
        btn.textContent = label;
      }
    });
  });
})();
