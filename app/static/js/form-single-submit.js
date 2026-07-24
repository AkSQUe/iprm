/* form-single-submit.js -- захист від подвійного сабміту.
   Форма з атрибутом data-single-submit після першого submit блокує кнопку
   та додає data-submitting, щоб CSS міг показати loading-стан. */
(function () {
  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  var forms = document.querySelectorAll('form[data-single-submit]');
  if (!forms.length) return;

  forms.forEach(function (form) {
    form.addEventListener('submit', function () {
      if (form.dataset.submitting === 'true') return;
      form.dataset.submitting = 'true';
      var buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
      buttons.forEach(function (btn) {
        btn.disabled = true;
        if (btn.dataset.defaultLabel === undefined && btn.textContent) {
          btn.dataset.defaultLabel = btn.textContent;
          btn.textContent = t('Надсилаємо…');
        }
      });
    });
  });
})();
