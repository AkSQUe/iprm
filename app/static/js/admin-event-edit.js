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

  // Program blocks: add / remove
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
