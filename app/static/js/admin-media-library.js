/* Адмін медіа-бібліотека: мультизавантаження у реєстр + інлайн-редагування alt.
   Без зовнішніх залежностей. Завантаження -> /admin/upload/media (без прив'язки),
   після завершення перезавантажуємо сторінку. Alt зберігається debounce-POST. */
(function () {
  'use strict';

  function notify(msg, type) {
    if (typeof window.iprmToast === 'function') window.iprmToast(msg, type || 'error');
    else if (type !== 'success') alert(msg);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var csrfEl = document.querySelector('input[name="csrf_token"]');
    var csrf = csrfEl ? csrfEl.value : '';

    // ---- Завантаження ----
    var zone = document.getElementById('media-upload');
    var input = document.getElementById('media-upload-input');
    if (zone && input) {
      var pending = 0;
      var succeeded = 0;

      var done = function () {
        pending -= 1;
        if (pending <= 0) {
          zone.classList.remove('media-upload--busy');
          // Перезавантажуємо, якщо хоч один файл завантажився -> часткові
          // успіхи видно одразу. Якщо всі впали -- лишаємось, щоб показати toast.
          if (succeeded > 0) window.location.reload();
        }
      };

      var uploadOne = function (file) {
        var okExt = /\.(png|jpe?g|webp|heic|heif)$/i.test(file.name);
        if (!okExt) { notify('Дозволені: PNG, JPG, WebP, HEIC'); return; }
        if (file.size > 25 * 1024 * 1024) { notify('Максимальний розмір: 25 MB'); return; }
        pending += 1;
        zone.classList.add('media-upload--busy');
        var fd = new FormData();
        fd.append('file', file);
        if (csrf) fd.append('csrf_token', csrf);
        fetch('/admin/upload/media', { method: 'POST', body: fd })
          .then(function (r) {
            if (r.status === 413) { notify('Файл завеликий (макс. 25 MB)'); return null; }
            return r.json().then(function (d) { return { ok: r.ok, d: d }; },
              function () { notify('Неочікувана відповідь сервера (' + r.status + ')'); return null; });
          })
          .then(function (res) {
            if (res && res.ok) { succeeded += 1; }
            else if (res && !res.ok) { notify(res.d.error || 'Помилка завантаження'); }
          })
          .catch(function () { notify('Помилка мережі'); })
          .then(done);
      };

      var handleFiles = function (files) {
        Array.prototype.slice.call(files).forEach(uploadOne);
      };

      zone.addEventListener('click', function () { input.click(); });
      input.addEventListener('change', function () { if (input.files.length) handleFiles(input.files); });
      zone.addEventListener('dragover', function (e) { e.preventDefault(); zone.classList.add('media-upload--drag'); });
      zone.addEventListener('dragleave', function () { zone.classList.remove('media-upload--drag'); });
      zone.addEventListener('drop', function (e) {
        e.preventDefault();
        zone.classList.remove('media-upload--drag');
        if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
      });
    }

    // ---- Інлайн alt ----
    var timers = {};
    document.querySelectorAll('.media-card__alt').forEach(function (inp) {
      inp.addEventListener('input', function () {
        var id = inp.getAttribute('data-id');
        clearTimeout(timers[id]);
        timers[id] = setTimeout(function () {
          var fd = new FormData();
          fd.append('alt', inp.value);
          if (csrf) fd.append('csrf_token', csrf);
          fetch('/admin/media/' + id + '/alt', { method: 'POST', body: fd })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { if (d && d.ok) { inp.classList.add('media-card__alt--saved'); setTimeout(function () { inp.classList.remove('media-card__alt--saved'); }, 800); } })
            .catch(function () {});
        }, 600);
      });
    });

    // ---- Мультивибір + bulk-видалення ----
    var checks = Array.prototype.slice.call(document.querySelectorAll('.media-card__check'));
    var bulkForm = document.getElementById('media-bulk-form');
    var bulkBtn = document.getElementById('media-bulk-delete');
    var selCount = document.getElementById('media-sel-count');
    var selectAll = document.getElementById('media-select-all');
    if (checks.length && bulkForm && bulkBtn) {
      var syncSelection = function () {
        // Прибираємо попередні ids
        Array.prototype.slice.call(bulkForm.querySelectorAll('input[name="ids"]')).forEach(function (el) { el.remove(); });
        var n = 0;
        checks.forEach(function (cb) {
          if (cb.checked) {
            n += 1;
            var h = document.createElement('input');
            h.type = 'hidden'; h.name = 'ids'; h.value = cb.value;
            bulkForm.appendChild(h);
          }
        });
        if (selCount) selCount.textContent = String(n);
        bulkBtn.disabled = n === 0;
      };
      checks.forEach(function (cb) { cb.addEventListener('change', syncSelection); });
      if (selectAll) {
        selectAll.addEventListener('change', function () {
          checks.forEach(function (cb) { cb.checked = selectAll.checked; });
          syncSelection();
        });
      }
      syncSelection();
    }
  });
})();
