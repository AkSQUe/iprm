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

    /* Повторний сабміт блокуємо, а не просто ігноруємо: кнопку могли й не
       вимкнути (див. нижче про зовнішні кнопки), і другий POST створив би
       ще одну реєстрацію з окремим рахунком. */
    if (form.dataset.submitting === 'true') {
      e.preventDefault();
      return;
    }
    form.dataset.submitting = 'true';
    var label = form.dataset.submittingLabel || t('Надсилаємо…');

    /* Кнопки бувають і ПОЗА формою -- прив'язані атрибутом form="<id>"
       (липка панель оплати на реєстрації). form.querySelectorAll шукає лише
       нащадків, тож така кнопка лишалась активною і дозволяла тиснути
       повторно, поки перший запит ще в дорозі. */
    var buttons = Array.prototype.slice.call(
      form.querySelectorAll('button[type="submit"], input[type="submit"]')
    );
    if (form.id) {
      var external = document.querySelectorAll(
        'button[form="' + form.id + '"], input[form="' + form.id + '"]'
      );
      Array.prototype.push.apply(buttons, Array.prototype.slice.call(external));
    }
    buttons.forEach(function (btn) {
      btn.disabled = true;
      if (btn.dataset.defaultLabel === undefined && btn.textContent) {
        btn.dataset.defaultLabel = btn.textContent;
        btn.textContent = label;
      }
    });
  });
})();
