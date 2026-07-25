/* confirm-action.js — підтвердження дій через стилізований модальний діалог.

   Розмітка:
     <form data-confirm="Точно вийти?">...           (на submit)
     <a   data-confirm="Видалити?" href="...">          (на click)
     <button data-confirm="...">                         (на click)

   Опціонально:
     data-confirm-ok="Так, вийти"      — текст кнопки підтвердження
     data-confirm-cancel="Скасувати"   — текст кнопки відміни
     data-confirm-danger               — червона кнопка підтвердження

   Домовленість (діє на всі виклики, не порушувати при додаванні нових):
     1. data-confirm-ok — завжди дієслово дії ("Видалити курс"), ніколи
        "Так"/"Підтвердити": кнопка сама має пояснювати, що станеться.
     2. data-confirm-danger — тільки для незворотних дій (видалення,
        перезапис даних, повернення коштів). Збереження налаштувань і
        надсилання листа червоними НЕ робимо, інакше червоний перестає
        читатися як попередження.
     3. Якщо кнопка відміни за змістом збігається з дією ("Скасувати
        реєстрацію"), задаємо data-confirm-cancel ("Не скасовувати").

   Vanilla JS, без залежностей. Single Responsibility. */
(function () {
  'use strict';

  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  var overlay = null;

  function buildOverlay() {
    overlay = document.createElement('div');
    overlay.className = 'iprm-confirm';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.hidden = true;
    overlay.innerHTML =
      '<div class="iprm-confirm__box" role="document">' +
        '<p class="iprm-confirm__msg"></p>' +
        '<div class="iprm-confirm__actions">' +
          '<button type="button" class="iprm-confirm__btn iprm-confirm__btn--cancel"></button>' +
          '<button type="button" class="iprm-confirm__btn iprm-confirm__btn--ok"></button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);
    return overlay;
  }

  function ensureOverlay() {
    if (!overlay || !document.body.contains(overlay)) buildOverlay();
    return overlay;
  }

  var _onResolve = null;

  function open(opts) {
    var ov = ensureOverlay();
    ov.querySelector('.iprm-confirm__msg').textContent = opts.message;
    var okBtn = ov.querySelector('.iprm-confirm__btn--ok');
    var cancelBtn = ov.querySelector('.iprm-confirm__btn--cancel');
    okBtn.textContent = opts.okText || t('Підтвердити');
    cancelBtn.textContent = opts.cancelText || t('Скасувати');
    okBtn.classList.toggle('iprm-confirm__btn--danger', !!opts.danger);

    ov.hidden = false;
    requestAnimationFrame(function () { ov.classList.add('is-visible'); });
    /* Небезпечні дії відкриваються з фокусом на "Скасувати": інакше Enter,
       натиснутий одразу після кнопки в таблиці, підтверджує знищення наосліп. */
    (opts.danger ? cancelBtn : okBtn).focus();
    _onResolve = opts.onResolve;
  }

  function close(result) {
    if (!overlay) return;
    overlay.classList.remove('is-visible');
    setTimeout(function () { if (overlay) overlay.hidden = true; }, 200);
    var cb = _onResolve;
    _onResolve = null;
    if (cb) cb(result);
  }

  // Делеговані обробники на overlay (живий після buildOverlay)
  document.addEventListener('click', function (e) {
    if (!overlay || overlay.hidden) return;
    if (e.target.closest('.iprm-confirm__btn--ok')) { close(true); }
    else if (e.target.closest('.iprm-confirm__btn--cancel')) { close(false); }
    else if (e.target === overlay) { close(false); }
  });
  document.addEventListener('keydown', function (e) {
    if (overlay && !overlay.hidden && e.key === 'Escape') close(false);
  });

  // Перехоплення submit-форм з data-confirm
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.matches('[data-confirm]')) return;
    if (form.__confirmed) { form.__confirmed = false; return; }
    e.preventDefault();
    open({
      message: form.getAttribute('data-confirm'),
      okText: form.getAttribute('data-confirm-ok'),
      cancelText: form.getAttribute('data-confirm-cancel'),
      danger: form.hasAttribute('data-confirm-danger'),
      onResolve: function (ok) {
        if (ok) {
          form.__confirmed = true;
          if (typeof form.requestSubmit === 'function') form.requestSubmit();
          else form.submit();
        }
      },
    });
  }, true);

  // Перехоплення кліків на посиланнях/кнопках з data-confirm
  document.addEventListener('click', function (e) {
    var el = e.target.closest('a[data-confirm], button[data-confirm]');
    if (!el) return;
    if (el.tagName === 'BUTTON' && el.type === 'submit') return; // обробить submit-listener форми
    if (el.__confirmed) { el.__confirmed = false; return; }
    e.preventDefault();
    open({
      message: el.getAttribute('data-confirm'),
      okText: el.getAttribute('data-confirm-ok'),
      cancelText: el.getAttribute('data-confirm-cancel'),
      danger: el.hasAttribute('data-confirm-danger'),
      onResolve: function (ok) {
        if (ok && el.tagName === 'A' && el.href) {
          window.location.href = el.href;
        } else if (ok) {
          el.__confirmed = true;
          el.click();
        }
      },
    });
  }, true);
})();
