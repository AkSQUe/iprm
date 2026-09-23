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
  // Переклад видимих рядків: словник i18n.js (app/js_strings.py) є лише на
  // публічних сторінках, тобто в кабінеті тренера. В адмінці його немає --
  // лишається український рядок, але з тими самими підстановками {name}:
  // фолбек "повернути ключ" показав би адміну буквальне {code}.
  function t(key, params) {
    if (window.iprmI18n && window.iprmI18n.t) return window.iprmI18n.t(key, params);
    if (!params) return key;
    return key.replace(/\{(\w+)\}/g, function(m, n) {
      return Object.prototype.hasOwnProperty.call(params, n) ? String(params[n]) : m;
    });
  }
  function notify(m) { if (typeof window.iprmToast === 'function') window.iprmToast(m, 'error'); else alert(m); }
  function parse(v) { try { var x = JSON.parse(v || '[]'); return Array.isArray(x) ? x : []; } catch (e) { return []; } }

  function mount(field, grid, fileInput, addBtn) {
    var uploadUrl = field.getAttribute('data-upload-url');
    var csrfEl = document.querySelector('input[name="csrf_token"]');
    var csrf = csrfEl ? csrfEl.value : '';
    var certs = parse(field.value);
    var dragFrom = null;
    // Завантажений файл уже на сервері, але в список тренера потрапляє лише
    // після «Зберегти»: хто йшов зі сторінки раніше, втрачав його мовчки.
    // Попереджаємо лише за справжньої зміни; відправка форми знімає прапорець.
    var dirty = false;
    var sync = function() { field.value = JSON.stringify(certs); dirty = true; };
    if (field.form) field.form.addEventListener('submit', function() { dirty = false; });
    window.addEventListener('beforeunload', function(e) {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = '';
    });
    // Перестановка кнопками «вище/нижче» -- для клавіатури й скрінрідера,
    // яким перетягування мишею недоступне. Після перерисовки фокус лишається
    // на тій самій картці (на кнопці, що перемістила її, а біля краю -- на
    // сусідній), інакше кожне натискання викидало б фокус на початок сторінки.
    var moveButtons = [];
    var move = function(from, dir) {
      var to = from + dir;
      if (to < 0 || to >= certs.length) return;
      var moved = certs.splice(from, 1)[0];
      certs.splice(to, 0, moved);
      render(); sync();
      var pair = moveButtons[to];
      var target = dir < 0 ? pair.up : pair.down;
      (target.disabled ? (dir < 0 ? pair.down : pair.up) : target).focus();
    };
    // Порожній стан малює шаблон (у кабінеті тренера), тут лише перемикання.
    // В адмінській картці тренера цього блоку немає -- звідси перевірка.
    var empty = document.getElementById('regalia-certs-empty');
    var render = function() {
      grid.innerHTML = '';
      moveButtons = [];
      if (empty) empty.hidden = certs.length > 0;
      certs.forEach(function(c, i) {
        var img = el('img', {'class': 'iprm-img-cover', src: c.thumb || c.url, alt: '', draggable: 'false'});
        var rm = el('button', {type: 'button', 'class': 'regalia-cert__remove', title: t('Видалити')}, [icon('close')]);
        rm.addEventListener('click', function() { certs.splice(i, 1); render(); sync(); });
        var cap = el('input', {'class': 'form-input regalia-cert__cap', type: 'text', placeholder: t('Підпис (необовʼязково)')});
        cap.value = c.caption || '';
        cap.addEventListener('input', function() { c.caption = cap.value; sync(); });
        // Перетягуємо за мініатюру (поле підпису лишається редагованим).
        var thumb = el('div', {'class': 'regalia-cert__thumb', draggable: 'true', title: t('Перетягніть, щоб змінити порядок')}, [img, rm]);
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
        var up = el('button', {type: 'button', 'class': 'regalia-cert__move regalia-cert__move-up',
                               'aria-label': t('Перемістити вище')});
        var down = el('button', {type: 'button', 'class': 'regalia-cert__move regalia-cert__move-down',
                                 'aria-label': t('Перемістити нижче')});
        // Стрілки -- звичайні символи (не шрифт іконок), як і "×" у кнопці
        // видалення: у кабінеті тренера адмінського шрифту іконок немає.
        up.textContent = '↑';
        down.textContent = '↓';
        up.disabled = i === 0;
        down.disabled = i === certs.length - 1;
        up.addEventListener('click', function() { move(i, -1); });
        down.addEventListener('click', function() { move(i, 1); });
        moveButtons.push({up: up, down: down});
        var order = el('div', {'class': 'regalia-cert__order'}, [up, down]);
        grid.appendChild(el('div', {'class': 'regalia-cert'}, [thumb, cap, order]));
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
      if (file.size > 25 * 1024 * 1024) { notify(t('Максимальний розмір: 25 MB')); return; }
      var fd = new FormData();
      fd.append('file', file);
      if (csrf) fd.append('csrf_token', csrf);
      addBtn.disabled = true;
      fetch(uploadUrl, {method: 'POST', body: fd})
        .then(function(r) {
          if (r.status === 413) { notify(t('Файл завеликий (макс. 25 MB)')); return null; }
          // 429 -- ліміт частоти завантажень у кабінеті: відповідь не JSON, і
          // без окремої гілки тренер бачив би «неочікувану відповідь сервера».
          if (r.status === 429) { notify(t('Забагато завантажень поспіль. Зачекайте хвилину й спробуйте ще раз.')); return null; }
          return r.json().then(function(d) { return {ok: r.ok, d: d}; }, function() {
            notify(t('Неочікувана відповідь сервера (код {code})', {code: r.status})); return null;
          });
        })
        .then(function(res) {
          if (!res) return;
          if (res.ok) { certs.push({url: res.d.url, thumb: res.d.thumb, card: res.d.card, media_id: res.d.media_id, caption: ''}); render(); sync(); }
          else notify(res.d.error || t('Помилка завантаження'));
        })
        .catch(function() { notify(t('Помилка мережі')); })
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
