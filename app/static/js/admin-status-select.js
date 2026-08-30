/* admin-status-select.js -- inline AJAX status change для <form data-status-form>.
   Progressive Enhancement: форма працює і без JS (submit -> redirect). */
(function () {
  var csrfToken = '';

  function init() {
    var csrfInput = document.querySelector('input[name="csrf_token"]');
    csrfToken = csrfInput ? csrfInput.value : '';

    document.querySelectorAll('form[data-status-form]').forEach(function (form) {
      var select = form.querySelector('select.badge-select');
      if (!select) return;
      select.setAttribute('data-prev-status', select.value);
    });
  }

  function getAllowedStatuses(select) {
    var set = {};
    Array.prototype.forEach.call(select.options, function (opt) { set[opt.value] = true; });
    return set;
  }

  function currentStatusClass(select) {
    for (var i = 0; i < select.classList.length; i++) {
      var cls = select.classList[i];
      if (cls.indexOf('badge-select--') === 0 && cls.indexOf('--flash-') === -1) {
        return cls;
      }
    }
    return '';
  }

  function setStatusClass(select, status) {
    var cur = currentStatusClass(select);
    if (cur) select.classList.remove(cur);
    select.classList.add('badge-select--' + status);
  }

  function flash(select, variant) {
    select.classList.remove('badge-select--flash-ok', 'badge-select--flash-err');
    var cls = 'badge-select--flash-' + variant;
    select.classList.add(cls);
    setTimeout(function () { select.classList.remove(cls); }, 1200);
  }

  // Тост -- через спільний API (toast.js), як і admin-inline-edit.js.
  function showToast(message, variant) {
    if (window.iprmToast) window.iprmToast(message, variant || 'info');
  }

  function handleChange(e) {
    var select = e.target;
    if (!select.classList || !select.classList.contains('badge-select')) return;
    var form = select.closest('form[data-status-form]');
    if (!form) return;

    var url = form.getAttribute('action');
    if (!url) return;

    var allowed = getAllowedStatuses(select);
    var prevStatus = select.getAttribute('data-prev-status') || '';
    var newStatus = select.value;

    if (!allowed[newStatus]) {
      select.value = prevStatus;
      showToast('Невідомий статус', 'error');
      return;
    }

    select.disabled = true;

    var formData = new FormData();
    formData.append('status', newStatus);
    formData.append('csrf_token', csrfToken);

    fetch(url, {
      method: 'POST',
      body: formData,
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json',
      },
    })
      .then(function (res) {
        return res.json()
          .catch(function () { return {}; })
          .then(function (data) { return { ok: res.ok, data: data }; });
      })
      .then(function (result) {
        select.disabled = false;
        var data = result.data || {};
        if (result.ok && data.ok && allowed[data.status]) {
          setStatusClass(select, data.status);
          select.setAttribute('data-prev-status', data.status);
          flash(select, 'ok');
          showToast('Статус оновлено: ' + (data.status_label || data.status), 'success');
        } else {
          select.value = prevStatus;
          flash(select, 'err');
          showToast(data.error || 'Не вдалося змінити статус', 'error');
        }
      })
      .catch(function () {
        select.disabled = false;
        select.value = prevStatus;
        flash(select, 'err');
        showToast('Помилка мережі', 'error');
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  document.addEventListener('change', handleChange);
})();
