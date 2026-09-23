/* Редактор сертифікатів-зображень тренера. Спільний для адмінки й кабінету:
   правка мусить доходити до обох, тож копії другого редактора тут бути не
   повинно. Адреса завантаження -- з data-upload-url на прихованому полі
   (адмінська й кабінетна сторінки ведуть на різні маршрути одного сервісу). */
(function () {
  'use strict';

  // Хелпери -- копія el/icon/notify/parse з admin-trainer-regalia.js: там
  // вони лишаються теж, бо потрібні патентам і статтям. Дублювання чотирьох
  // дрібних функцій дешевше за третій файл-утиліту заради них.
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function(k) {
      if (k === 'class') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function(c) { if (c) n.appendChild(c); });
    return n;
  }
  // На відміну від копії в admin-trainer-regalia.js, ця функція живе на
  // ДВОХ сторінках: в адмінці window.msGlyph/IPRM_ICONS є (base_admin.html),
  // у кабінеті тренера (base.html) -- нема, бо шрифт іконок підключає лише
  // адмінський каркас. Фолбек на сиру назву ('close') показував би саме
  // слово замість кнопки -- замість цього символ "×", та сама заглушка, що
  // й .iprm-lightbox__close у lightbox.js: не залежить від жодного шрифту.
  // Єдиний виклик у цьому файлі -- icon('close'), тож інших назв тут нема.
  function icon(name) {
    var s = el('span', {'class': 'material-symbols-rounded', 'aria-hidden': 'true'});
    s.textContent = window.msGlyph ? window.msGlyph(name) : '×';
    return s;
  }
  function notify(m) { if (typeof window.iprmToast === 'function') window.iprmToast(m, 'error'); else alert(m); }
  function parse(v) { try { var x = JSON.parse(v || '[]'); return Array.isArray(x) ? x : []; } catch (e) { return []; } }

  function mount(field, grid, fileInput, addBtn) {
    var uploadUrl = field.getAttribute('data-upload-url');
    var csrfEl = document.querySelector('input[name="csrf_token"]');
    var csrf = csrfEl ? csrfEl.value : '';
    var certs = parse(field.value);
    var dragFrom = null;
    var sync = function() { field.value = JSON.stringify(certs); };
    var render = function() {
      grid.innerHTML = '';
      certs.forEach(function(c, i) {
        var img = el('img', {'class': 'iprm-img-cover', src: c.thumb || c.url, alt: '', draggable: 'false'});
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
    // Без 'slug' у формі: адмінський маршрут його ніколи не читав (лише
    // process_trainer_signature потребує slug для імені файлу), а в кабінеті
    // тренера взагалі немає полів #slug/#full_name, з яких його брати.
    var uploadCert = function(file) {
      if (file.size > 25 * 1024 * 1024) { notify('Максимальний розмір: 25 MB'); return; }
      var fd = new FormData();
      fd.append('file', file);
      if (csrf) fd.append('csrf_token', csrf);
      addBtn.disabled = true;
      fetch(uploadUrl, {method: 'POST', body: fd})
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

  document.addEventListener('DOMContentLoaded', function () {
    var field = document.getElementById('regalia-cert-field');
    var grid = document.getElementById('regalia-certs-grid');
    var fileInput = document.getElementById('regalia-cert-file');
    var addBtn = document.getElementById('regalia-cert-add');
    if (field && grid && fileInput && addBtn) mount(field, grid, fileInput, addBtn);
  });
})();
