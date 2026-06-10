/* Редактор регалій тренера (admin): сертифікати-зображення + повторювані
   списки посилань (патенти, статті). Серіалізує у приховані JSON-поля.
   Сервер усе одно санітизує -- тут лише зручність. Без зовнішніх залежностей. */
(function() {
  'use strict';

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function(k) {
      if (k === 'class') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function(c) { if (c) n.appendChild(c); });
    return n;
  }
  function icon(name) { var s = el('span', {'class': 'material-symbols-rounded'}); s.textContent = name; return s; }
  function notify(m) { if (typeof window.iprmToast === 'function') window.iprmToast(m, 'error'); else alert(m); }
  function parse(v) { try { var x = JSON.parse(v || '[]'); return Array.isArray(x) ? x : []; } catch (e) { return []; } }

  document.addEventListener('DOMContentLoaded', function() {
    var csrfEl = document.querySelector('input[name="csrf_token"]');
    var csrf = csrfEl ? csrfEl.value : '';
    var slugEl = document.getElementById('slug');
    var nameEl = document.getElementById('full_name');
    function getSlug() {
      return (slugEl && slugEl.value.trim()) || (nameEl && nameEl.value.trim()) || 'trainer';
    }

    // ---- Сертифікати (зображення) ----
    var certField = document.getElementById('regalia-cert-field');
    var grid = document.getElementById('regalia-certs-grid');
    var fileInput = document.getElementById('regalia-cert-file');
    var addBtn = document.getElementById('regalia-cert-add');
    if (certField && grid && fileInput && addBtn) {
      var certs = parse(certField.value);
      var dragFrom = null;
      var sync = function() { certField.value = JSON.stringify(certs); };
      var render = function() {
        grid.innerHTML = '';
        certs.forEach(function(c, i) {
          var img = el('img', {src: c.thumb || c.url, alt: '', draggable: 'false'});
          var rm = el('button', {type: 'button', 'class': 'regalia-cert__remove', title: 'Видалити'}, [icon('close')]);
          rm.addEventListener('click', function() { certs.splice(i, 1); render(); sync(); });
          var cap = el('input', {'class': 'form-input regalia-cert__cap', type: 'text', placeholder: 'Підпис (необовʼязково)'});
          cap.value = c.caption || '';
          cap.addEventListener('input', function() { c.caption = cap.value; sync(); });
          // Перетягуємо за мініатюру (поле підпису лишається редагованим).
          var thumb = el('div', {'class': 'regalia-cert__thumb', draggable: 'true', title: 'Перетягніть, щоб змінити порядок'}, [img, rm]);
          thumb.addEventListener('dragstart', function(e) {
            dragFrom = i; thumb.classList.add('regalia-cert__thumb--drag');
            if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(i)); }
          });
          thumb.addEventListener('dragend', function() { thumb.classList.remove('regalia-cert__thumb--drag'); dragFrom = null; });
          thumb.addEventListener('dragover', function(e) { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'; });
          thumb.addEventListener('drop', function(e) {
            e.preventDefault();
            if (dragFrom === null || dragFrom === i) return;
            var moved = certs.splice(dragFrom, 1)[0];
            certs.splice(i, 0, moved);
            render(); sync();
          });
          grid.appendChild(el('div', {'class': 'regalia-cert'}, [thumb, cap]));
        });
      };
      render();
      addBtn.addEventListener('click', function() { fileInput.click(); });
      fileInput.addEventListener('change', function() {
        Array.prototype.slice.call(fileInput.files).forEach(uploadCert);
        fileInput.value = '';
      });
      var uploadCert = function(file) {
        if (file.size > 25 * 1024 * 1024) { notify('Максимальний розмір: 25 MB'); return; }
        var fd = new FormData();
        fd.append('file', file);
        fd.append('slug', getSlug());
        if (csrf) fd.append('csrf_token', csrf);
        addBtn.disabled = true;
        fetch('/admin/upload/trainer-certificate', {method: 'POST', body: fd})
          .then(function(r) {
            if (r.status === 413) { notify('Файл завеликий (макс. 25 MB)'); return null; }
            return r.json().then(function(d) { return {ok: r.ok, d: d}; }, function() {
              notify('Неочікувана відповідь сервера (код ' + r.status + ')'); return null;
            });
          })
          .then(function(res) {
            if (!res) return;
            if (res.ok) { certs.push({url: res.d.url, thumb: res.d.thumb, card: res.d.card, media_id: res.d.media_id, caption: ''}); render(); sync(); }
            else notify(res.d.error || 'Помилка завантаження');
          })
          .catch(function() { notify('Помилка мережі'); })
          .then(function() { addBtn.disabled = false; });
      };
    }

    // ---- Повторювані списки посилань (патенти, статті) ----
    // Опційно з зображеннями (data-images="1"): кожен рядок може мати скан,
    // під яким на сайті показується назва-посилання (патенти).
    Array.prototype.forEach.call(document.querySelectorAll('.regalia-links'), function(wrap) {
      var field = document.getElementById(wrap.getAttribute('data-target'));
      var rowsBox = wrap.querySelector('.regalia-links__rows');
      var addBtn2 = wrap.querySelector('.regalia-links__add');
      if (!field || !rowsBox || !addBtn2) return;
      var withImages = wrap.getAttribute('data-images') === '1';

      var syncLinks = function() {
        var links = Array.prototype.map.call(rowsBox.querySelectorAll('.regalia-link'), function(row) {
          var o = {
            label: row.querySelector('.regalia-link__label').value.trim(),
            url: row.querySelector('.regalia-link__url').value.trim(),
          };
          if (withImages) {
            o.image = row.dataset.image || '';
            o.thumb = row.dataset.thumb || '';
            if (row.dataset.card) o.card = row.dataset.card;
            if (row.dataset.media) o.media_id = row.dataset.media;
          }
          return o;
        }).filter(function(l) { return l.url || l.image; });
        field.value = JSON.stringify(links);
      };

      var addRow = function(data) {
        data = data || {};
        var row = el('div', {'class': 'regalia-link' + (withImages ? ' regalia-link--img' : '')});

        if (withImages) {
          row.dataset.image = data.image || '';
          row.dataset.thumb = data.thumb || '';
          if (data.card) row.dataset.card = data.card;
          if (data.media_id) row.dataset.media = data.media_id;
          var img = el('img', {'class': 'regalia-link__thumb-img', alt: ''});
          var setThumb = function() {
            var src = row.dataset.thumb || row.dataset.image;
            if (src) { img.src = src; img.style.display = ''; }
            else { img.removeAttribute('src'); img.style.display = 'none'; }
          };
          setThumb();
          var fileIn = el('input', {type: 'file', 'class': 'regalia-hidden-file',
            accept: 'image/png,image/jpeg,image/webp,.heic,.heif'});
          var upBtn = el('button', {type: 'button', 'class': 'regalia-link__upload', title: 'Завантажити скан'}, [icon('add_photo_alternate')]);
          upBtn.addEventListener('click', function() { fileIn.click(); });
          fileIn.addEventListener('change', function() {
            var f = fileIn.files[0]; fileIn.value = '';
            if (!f) return;
            if (f.size > 25 * 1024 * 1024) { notify('Максимальний розмір: 25 MB'); return; }
            var fd = new FormData();
            fd.append('file', f); fd.append('slug', getSlug());
            if (csrf) fd.append('csrf_token', csrf);
            upBtn.disabled = true;
            fetch('/admin/upload/trainer-certificate', {method: 'POST', body: fd})
              .then(function(r) {
                if (r.status === 413) { notify('Файл завеликий (макс. 25 MB)'); return null; }
                return r.json().then(function(d) { return {ok: r.ok, d: d}; }, function() {
                  notify('Неочікувана відповідь сервера (код ' + r.status + ')'); return null;
                });
              })
              .then(function(res) {
                if (!res) return;
                if (res.ok) {
                  row.dataset.image = res.d.url;
                  row.dataset.thumb = res.d.thumb || res.d.url;
                  if (res.d.card) row.dataset.card = res.d.card;
                  if (res.d.media_id) row.dataset.media = res.d.media_id;
                  setThumb(); syncLinks();
                }
                else notify(res.d.error || 'Помилка завантаження');
              })
              .catch(function() { notify('Помилка мережі'); })
              .then(function() { upBtn.disabled = false; });
          });
          row.appendChild(el('div', {'class': 'regalia-link__thumb'}, [img, upBtn, fileIn]));
        }

        var label = el('input', {'class': 'form-input regalia-link__label', type: 'text', placeholder: 'Назва'});
        label.value = data.label || '';
        var url = el('input', {'class': 'form-input regalia-link__url', type: 'url', placeholder: 'https://... (необовʼязково)'});
        url.value = data.url || '';
        var up = el('button', {type: 'button', 'class': 'regalia-link__move', title: 'Вгору'}, [icon('keyboard_arrow_up')]);
        var down = el('button', {type: 'button', 'class': 'regalia-link__move', title: 'Вниз'}, [icon('keyboard_arrow_down')]);
        var rm = el('button', {type: 'button', 'class': 'regalia-link__remove', title: 'Видалити'}, [icon('close')]);
        up.addEventListener('click', function() { var prev = row.previousElementSibling; if (prev) { rowsBox.insertBefore(row, prev); syncLinks(); } });
        down.addEventListener('click', function() { var next = row.nextElementSibling; if (next) { rowsBox.insertBefore(next, row); syncLinks(); } });
        rm.addEventListener('click', function() { rowsBox.removeChild(row); syncLinks(); });
        label.addEventListener('input', syncLinks);
        url.addEventListener('input', syncLinks);
        row.appendChild(label); row.appendChild(url); row.appendChild(up); row.appendChild(down); row.appendChild(rm);
        rowsBox.appendChild(row);
      };
      parse(field.value).forEach(addRow);
      addBtn2.addEventListener('click', function() { addRow({}); });
    });
  });
})();
