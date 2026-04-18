/* Shared image-dropzone handler for admin forms.
   Requires markup per .admin-dropzone convention (see admin-apple.css).
   Caller must provide: upload endpoint URL, slug source function. */
(function() {
  window.initAdminDropzones = function(opts) {
    var endpoint = opts.endpoint;
    var getSlug = opts.getSlug;
    var slugMissingMsg = opts.slugMissingMsg || 'Спочатку вкажіть slug';

    var dropzones = document.querySelectorAll('.admin-dropzone');
    var csrfToken = document.querySelector('input[name="csrf_token"]');

    dropzones.forEach(function(zone) {
      var fileInput = zone.querySelector('.admin-dropzone__input');
      var prompt = zone.querySelector('.admin-dropzone__prompt');
      var preview = zone.querySelector('.admin-dropzone__preview');
      var previewImg = preview.querySelector('img');
      var removeBtn = zone.querySelector('.admin-dropzone__remove');
      var targetId = zone.getAttribute('data-target');
      var hiddenInput = document.getElementById(targetId);

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
        hiddenInput.value = '';
        preview.classList.remove('admin-dropzone__preview--active');
        if (previewImg) previewImg.src = '';
        prompt.classList.remove('admin-dropzone__prompt--hidden');
      });

      function uploadFile(file) {
        var allowed = ['image/png', 'image/jpeg', 'image/webp'];
        if (allowed.indexOf(file.type) === -1) {
          alert('Дозволені формати: PNG, JPG, WebP');
          return;
        }
        if (file.size > 5 * 1024 * 1024) {
          alert('Максимальний розмір: 5 MB');
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
          alert(slugMissingMsg);
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
        .then(function(res) { return res.json().then(function(data) { return {ok: res.ok, data: data}; }); })
        .then(function(result) {
          zone.classList.remove('admin-dropzone--uploading');
          if (result.ok) {
            hiddenInput.value = result.data.url;
          } else {
            alert(result.data.error || 'Помилка завантаження');
            if (!hiddenInput.value) {
              preview.classList.remove('admin-dropzone__preview--active');
              prompt.classList.remove('admin-dropzone__prompt--hidden');
            }
          }
        })
        .catch(function() {
          zone.classList.remove('admin-dropzone--uploading');
          alert('Помилка мережі');
        });
      }
    });
  };
})();
