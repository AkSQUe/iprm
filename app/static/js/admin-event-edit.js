(function() {
  // Auto-slug from title
  var titleInput = document.getElementById('title');
  var slugInput = document.getElementById('slug');
  if (titleInput && slugInput) {
    var slugManuallyEdited = slugInput.value.length > 0;

    slugInput.addEventListener('input', function() {
      slugManuallyEdited = true;
    });

    titleInput.addEventListener('input', function() {
      if (slugManuallyEdited) return;
      var text = titleInput.value.toLowerCase().trim();
      text = text.replace(/[^\w\s-]/g, '');
      text = text.replace(/[\s_]+/g, '-');
      text = text.replace(/-+/g, '-');
      slugInput.value = text.substring(0, 200);
    });
  }

  // ========== IMAGE DROPZONE ==========

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

    // Клік на зону -- відкрити файловий діалог
    zone.addEventListener('click', function(e) {
      if (e.target === removeBtn || e.target.closest('.admin-dropzone__remove')) return;
      fileInput.click();
    });

    // Вибір файлу через діалог
    fileInput.addEventListener('change', function() {
      if (fileInput.files.length) uploadFile(fileInput.files[0]);
    });

    // Drag & drop
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

    // Видалення зображення
    removeBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      hiddenInput.value = '';
      preview.classList.remove('admin-dropzone__preview--active');
      if (previewImg) previewImg.src = '';
      prompt.classList.remove('admin-dropzone__prompt--hidden');
    });

    function uploadFile(file) {
      // Валідація на клієнті
      var allowed = ['image/png', 'image/jpeg', 'image/webp'];
      if (allowed.indexOf(file.type) === -1) {
        alert('Дозволені формати: PNG, JPG, WebP');
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        alert('Максимальний розмір: 5 MB');
        return;
      }

      // Локальний preview
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

      // Upload на сервер
      var slug = slugInput ? slugInput.value.trim() : '';
      if (!slug) {
        alert('Спочатку вкажіть slug курсу');
        return;
      }

      zone.classList.add('admin-dropzone--uploading');

      var formData = new FormData();
      formData.append('file', file);
      formData.append('slug', slug);
      if (csrfToken) formData.append('csrf_token', csrfToken.value);

      fetch('/admin/upload/course-image', {
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
          // Повертаємо prompt якщо раніше не було зображення
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

  // ========== PROGRAM BLOCKS ==========

  var container = document.getElementById('program-blocks');
  var addBtn = document.getElementById('add-program-block');
  if (!container || !addBtn) return;

  function getNextIndex() {
    var blocks = container.querySelectorAll('.admin-program-block');
    var max = -1;
    for (var i = 0; i < blocks.length; i++) {
      var idx = parseInt(blocks[i].getAttribute('data-index'), 10);
      if (idx > max) max = idx;
    }
    return max + 1;
  }

  function bindRemoveButtons() {
    var btns = container.querySelectorAll('.admin-program-block__remove');
    for (var i = 0; i < btns.length; i++) {
      btns[i].onclick = function() {
        this.closest('.admin-program-block').remove();
        reindex();
      };
    }
  }

  function reindex() {
    var blocks = container.querySelectorAll('.admin-program-block');
    for (var i = 0; i < blocks.length; i++) {
      blocks[i].setAttribute('data-index', i);
      var idInput = blocks[i].querySelector('input[type="hidden"]');
      if (idInput) idInput.name = 'block_' + i + '_id';
      var headingInput = blocks[i].querySelector('input[type="text"]');
      if (headingInput) headingInput.name = 'block_' + i + '_heading';
      var itemsArea = blocks[i].querySelector('textarea');
      if (itemsArea) itemsArea.name = 'block_' + i + '_items';
    }
  }

  addBtn.addEventListener('click', function() {
    var idx = getNextIndex();
    var div = document.createElement('div');
    div.className = 'admin-program-block';
    div.setAttribute('data-index', idx);
    div.innerHTML =
      '<div class="admin-form__grid">' +
        '<div class="form-group admin-form__full">' +
          '<label>Заголовок блоку <span class="required">*</span></label>' +
          '<div class="admin-program-block__header">' +
            '<input type="text" name="block_' + idx + '_heading" class="form-input" placeholder="Теоретична частина">' +
            '<button type="button" class="btn-admin btn-admin--danger btn-admin--sm admin-program-block__remove">X</button>' +
          '</div>' +
        '</div>' +
        '<div class="form-group admin-form__full">' +
          '<label>Пункти програми</label>' +
          '<textarea name="block_' + idx + '_items" class="form-input" rows="5" placeholder="Один пункт на рядок"></textarea>' +
          '<div class="form-hint">Кожен рядок стане окремим пунктом списку</div>' +
        '</div>' +
      '</div>';
    container.appendChild(div);
    bindRemoveButtons();
  });

  bindRemoveButtons();
})();
