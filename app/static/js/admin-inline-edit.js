/* admin-inline-edit.js -- зміна статусу/оплати реєстрації прямо в таблиці.

   <select data-inline-url data-inline-field data-csrf> при change шле fetch-POST,
   на успіх -- підсвічує клітинку й оновлює колір/№ місця, на помилку --
   відкочує значення. data-state зберігає поточне значення для відкату. */
(function () {
  'use strict';

  function flash(el, ok) {
    el.classList.remove('is-saved', 'is-error');
    // reflow, щоб анімація перезапускалась при повторних змінах
    void el.offsetWidth;
    el.classList.add(ok ? 'is-saved' : 'is-error');
    setTimeout(function () { el.classList.remove('is-saved', 'is-error'); }, 1400);
  }

  document.addEventListener('change', function (e) {
    var sel = e.target.closest('select[data-inline-url]');
    if (!sel) return;

    var url = sel.getAttribute('data-inline-url');
    var field = sel.getAttribute('data-inline-field');
    var csrf = sel.getAttribute('data-csrf') || '';
    var prev = sel.getAttribute('data-state');  // значення до зміни (для відкату)
    var value = sel.value;

    sel.disabled = true;
    var body = new URLSearchParams();
    body.append(field, value);

    fetch(url, {
      method: 'POST',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrf,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      credentials: 'same-origin',
      body: body.toString(),
    })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (!r.ok || !d.ok) throw new Error((d && d.error) || 'error');
          return d;
        });
      })
      .then(function (d) {
        sel.setAttribute('data-state', value);  // фіксуємо нове значення
        flash(sel, true);
        // Оновити колонку місця, якщо оплата призначила номер.
        if (d.place_number) {
          var row = sel.closest('tr');
          var cell = row && row.querySelector('[data-place-cell]');
          if (cell) cell.innerHTML = '<strong>№' + d.place_number + '</strong>';
        }
      })
      .catch(function () {
        sel.value = prev;  // відкат до попереднього значення
        flash(sel, false);
        if (window.iprmToast) {
          window.iprmToast('Не вдалося оновити. Спробуйте ще раз.', 'error');
        }
      })
      .finally(function () { sel.disabled = false; });
  });
})();
