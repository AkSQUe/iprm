/* Shared image-dropzone handler for admin forms.
   Requires markup per .admin-dropzone convention (see admin-apple.css).
   Caller must provide: upload endpoint URL, slug source function. */
(function() {
  /* Сповіщення через toast-систему сайту (window.iprmToast), а не нативний
     alert(). Фолбек на alert лише якщо toast чомусь недоступний. */
  function notifyError(msg) {
    if (typeof window.iprmToast === 'function') {
      window.iprmToast(msg, 'error');
    } else {
      alert(msg);
    }
  }

  window.initAdminDropzones = function(opts) {
    var endpoint = opts.endpoint;
    var getSlug = opts.getSlug;
    var slugMissingMsg = opts.slugMissingMsg || 'Спочатку вкажіть slug';
    // Дозволені типи можна перевизначити (напр. блог приймає HEIC). За
    // замовчуванням -- як раніше (PNG/JPG/WebP), щоб не ламати інших викликів.
    var allowedTypes = opts.allowed || ['image/png', 'image/jpeg', 'image/webp'];
    var allowedExt = opts.allowedExt || null;  // RegExp на ім'я файлу (для HEIC, де type порожній)
    var allowedMsg = opts.allowedMsg || 'Дозволені формати: PNG, JPG, WebP';
    var maxBytes = opts.maxBytes || 5 * 1024 * 1024;
    var maxMsg = opts.maxMsg || 'Максимальний розмір: 5 MB';

    var dropzones = document.querySelectorAll('.admin-dropzone');
    var csrfToken = document.querySelector('input[name="csrf_token"]');

    dropzones.forEach(function(zone) {
      var fileInput = zone.querySelector('.admin-dropzone__input');
      var prompt = zone.querySelector('.admin-dropzone__prompt');
      var preview = zone.querySelector('.admin-dropzone__preview');
      var previewImg = preview.querySelector('img');
      var removeBtn = zone.querySelector('.admin-dropzone__remove');
      // URL-поле (data-target) опційне -- після Фази 6 dropzone'и зберігають
      // лише media_id (data-target-media); URL більше не персиститься у формі.
      var targetId = zone.getAttribute('data-target');
      var hiddenInput = targetId ? document.getElementById(targetId) : null;
      var mediaTargetId = zone.getAttribute('data-target-media');
      var mediaInput = mediaTargetId ? document.getElementById(mediaTargetId) : null;

      zone.addEventListener('click', function(e) {
        if (e.target === removeBtn || e.target.closest('.admin-dropzone__remove')) return;
        fileInput.click();
      });

      fileInput.addEventListener('change', function() {
        if (fileInput.files.length) uploadFile(fileInput.files[0]);
      });

      zone.addEventListener('dragover', function(e) {
        e.preventDefault();
        zone.classList.add('admin-dropzone--dragover');
      });

      zone.addEventListener('dragleave', function() {
        zone.classList.remove('admin-dropzone--dragover');
      });

      zone.addEventListener('drop', function(e) {
        e.preventDefault();
        zone.classList.remove('admin-dropzone--dragover');
        var files = e.dataTransfer.files;
        if (files.length) uploadFile(files[0]);
      });

      removeBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (hiddenInput) hiddenInput.value = '';
        if (mediaInput) mediaInput.value = '';
        preview.classList.remove('admin-dropzone__preview--active');
        if (previewImg) previewImg.src = '';
        prompt.classList.remove('admin-dropzone__prompt--hidden');
      });

      function uploadFile(file) {
        if (allowedTypes.indexOf(file.type) === -1 && !(allowedExt && allowedExt.test(file.name))) {
          notifyError(allowedMsg);
          return;
        }
        if (file.size > maxBytes) {
          notifyError(maxMsg);
          return;
        }

        var reader = new FileReader();
        reader.onload = function(e) {
          if (!previewImg) {
            previewImg = document.createElement('img');
            previewImg.alt = 'Preview';
            preview.insertBefore(previewImg, preview.firstChild);
          }
          previewImg.src = e.target.result;
          preview.classList.add('admin-dropzone__preview--active');
          prompt.classList.add('admin-dropzone__prompt--hidden');
        };
        reader.readAsDataURL(file);

        var slug = getSlug();
        if (!slug) {
          notifyError(slugMissingMsg);
          return;
        }

        zone.classList.add('admin-dropzone--uploading');

        var formData = new FormData();
        formData.append('file', file);
        formData.append('slug', slug);
        if (csrfToken) formData.append('csrf_token', csrfToken.value);

        fetch(endpoint, {
          method: 'POST',
          body: formData
        })
        .then(function(res) {
          if (res.status === 413) { return {ok: false, data: {error: 'Сервер відхилив файл (413): імовірно, ліміт nginx (client_max_body_size).'}}; }
          // Не-JSON відповідь (HTML-помилка / редірект на логін) -> керована помилка
          return res.json().then(
            function(data) { return {ok: res.ok, data: data}; },
            function() { return {ok: false, data: {error: 'Неочікувана відповідь сервера (код ' + res.status + ')'}}; }
          );
        })
        .then(function(result) {
          zone.classList.remove('admin-dropzone--uploading');
          if (result.ok) {
            if (hiddenInput) hiddenInput.value = result.data.url;
            if (mediaInput) mediaInput.value = result.data.media_id || '';
            // Оновлюємо прев'ю реальним результатом із сервера: для HEIC
            // локальний FileReader не рендериться, тож показуємо WebP-відповідь.
            if (previewImg && (result.data.thumb || result.data.url)) {
              previewImg.src = result.data.thumb || result.data.url;
            }
          } else {
            notifyError(result.data.error || 'Помилка завантаження');
            var hasValue = (hiddenInput && hiddenInput.value) || (mediaInput && mediaInput.value);
            if (!hasValue) {
              preview.classList.remove('admin-dropzone__preview--active');
              prompt.classList.remove('admin-dropzone__prompt--hidden');
            }
          }
        })
        .catch(function() {
          zone.classList.remove('admin-dropzone--uploading');
          notifyError('Помилка мережі');
        });
      }
    });
  };
})();
