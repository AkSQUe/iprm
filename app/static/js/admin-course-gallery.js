/* admin-course-gallery.js -- редактор галереї курсу (адмінка).
 *
 * Фото галереї живуть у медіа-реєстрі (MediaFile з usage_type='gallery'), а
 * не в JSON курсу. Тому редактор оперує лише порядком і підписами:
 * завантажує файл через спільний ендпоінт /admin/upload/media, а в приховане
 * поле кладе [{media_id, caption, thumb}]. Прив'язку до курсу і sort_order
 * проставляє сервер під час збереження форми.
 *
 * Без зовнішніх залежностей, як і решта адмінських редакторів.
 */
(function () {
  'use strict';

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === 'class') node.className = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (kids || []).forEach(function (kid) { if (kid) node.appendChild(kid); });
    return node;
  }

  function notify(message) {
    if (typeof window.iprmToast === 'function') window.iprmToast(message, 'error');
    else alert(message);
  }

  function parse(value) {
    try {
      var data = JSON.parse(value || '[]');
      return Array.isArray(data) ? data : [];
    } catch (e) {
      return [];
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var root = document.querySelector('[data-gallery-editor]');
    var field = document.querySelector('[data-gallery-field]');
    if (!root || !field) return;

    var grid = root.querySelector('[data-gallery-grid]');
    var fileInput = root.querySelector('[data-gallery-file]');
    var addBtn = root.querySelector('[data-gallery-add]');
    if (!grid || !fileInput || !addBtn) return;

    var csrfEl = document.querySelector('input[name="csrf_token"]');
    var csrf = csrfEl ? csrfEl.value : '';
    var uploadUrl = root.getAttribute('data-upload-url');
    var entityType = root.getAttribute('data-entity-type') || '';
    var entityId = root.getAttribute('data-entity-id') || '';

    var items = parse(field.value);
    var dragFrom = null;

    function sync() {
      field.value = JSON.stringify(items);
    }

    function render() {
      grid.textContent = '';
      items.forEach(function (item, index) {
        var img = el('img', {
          'class': 'admin-gallery__thumb',
          src: item.thumb || item.url || '',
          alt: '',
        });

        var caption = el('input', {
          'class': 'form-input admin-gallery__caption',
          type: 'text',
          maxlength: '255',
          placeholder: 'Підпис під фото',
          value: item.caption || '',
        });
        caption.addEventListener('input', function () {
          items[index].caption = caption.value;
          sync();
        });

        var remove = el('button', {
          'class': 'btn-admin btn-admin--danger btn-admin--sm admin-gallery__remove',
          type: 'button',
          'aria-label': 'Прибрати з галереї',
        });
        remove.textContent = '×';
        remove.addEventListener('click', function () {
          items.splice(index, 1);
          sync();
          render();
        });

        var card = el('div', {
          'class': 'admin-gallery__item',
          draggable: 'true',
        }, [img, caption, remove]);

        // Перетягування міняє порядок показу на сайті (sort_order).
        card.addEventListener('dragstart', function () { dragFrom = index; });
        card.addEventListener('dragover', function (event) { event.preventDefault(); });
        card.addEventListener('drop', function (event) {
          event.preventDefault();
          if (dragFrom === null || dragFrom === index) return;
          var moved = items.splice(dragFrom, 1)[0];
          items.splice(index, 0, moved);
          dragFrom = null;
          sync();
          render();
        });

        grid.appendChild(card);
      });
    }

    function upload(file) {
      var data = new FormData();
      data.append('file', file);
      data.append('usage_type', 'gallery');
      // Токен і полем, і заголовком -- як у admin-dropzone.js, що вантажить
      // у той самий ендпоінт.
      if (csrf) data.append('csrf_token', csrf);
      // entity_* передаємо одразу, коли курс уже існує: інакше файл висів би
      // у реєстрі без власника до першого збереження форми.
      if (entityType) data.append('entity_type', entityType);
      if (entityId) data.append('entity_id', entityId);

      return fetch(uploadUrl, {
        method: 'POST',
        body: data,
        headers: { 'X-CSRFToken': csrf },
        credentials: 'same-origin',
      }).then(function (response) {
        return response.json().then(function (payload) {
          if (!response.ok) throw new Error(payload.error || 'Помилка завантаження');
          return payload;
        });
      }).then(function (payload) {
        items.push({
          media_id: payload.id,
          caption: '',
          thumb: payload.thumb || payload.url,
        });
        sync();
        render();
      });
    }

    addBtn.addEventListener('click', function () { fileInput.click(); });

    fileInput.addEventListener('change', function () {
      var files = Array.prototype.slice.call(fileInput.files || []);
      // Послідовно, а не Promise.all: пачка великих фото паралельно
      // упирається в ліміти сервера, а порядок додавання стає випадковим.
      files.reduce(function (chain, file) {
        return chain.then(function () { return upload(file); })
          .catch(function (error) { notify(error.message); });
      }, Promise.resolve()).then(function () { fileInput.value = ''; });
    });

    render();
  });
})();
