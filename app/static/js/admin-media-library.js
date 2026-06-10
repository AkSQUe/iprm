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
      var hadError = false;

      var done = function () {
        pending -= 1;
        if (pending <= 0) {
          zone.classList.remove('media-upload--busy');
          if (!hadError) window.location.reload();
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
            if (r.status === 413) { notify('Файл завеликий (макс. 25 MB)'); hadError = true; return null; }
            return r.json().then(function (d) { return { ok: r.ok, d: d }; },
              function () { notify('Неочікувана відповідь сервера (' + r.status + ')'); hadError = true; return null; });
          })
          .then(function (res) {
            if (res && !res.ok) { hadError = true; notify(res.d.error || 'Помилка завантаження'); }
          })
          .catch(function () { hadError = true; notify('Помилка мережі'); })
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
  });
})();
