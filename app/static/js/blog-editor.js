/* Блочний редактор блогу (vanilla, без зовнішніх залежностей).
   Працює з прихованим полем content: при сабміті форми серіалізує блоки у JSON.
   Сервер усе одно санітизує -- тут лише зручність редагування.

   Блоки: heading, paragraph, list, quote, image, gallery, youtube, callout, divider.
   API: window.initBlogEditor({mount, addBar, field, form, uploadEndpoint, getSlug}). */
(function() {
  'use strict';

  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function(k) {
      if (k === 'class') n.className = attrs[k];
      else if (k === 'html') n.innerHTML = attrs[k];
      else if (k === 'text') n.textContent = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function(c) {
      if (typeof c === 'string') n.appendChild(document.createTextNode(c));
      else if (c) n.appendChild(c);
    });
    return n;
  }

  // Субсет-шрифт без лігатур: рендеримо іконку через КОДПОЙНТ (window.msGlyph),
  // інакше показувався б сирий текст назви (base_admin.html задає IPRM_ICONS).
  function icon(name) { return el('span', {'class': 'material-symbols-rounded', text: (window.msGlyph ? window.msGlyph(name) : name)}); }

  function notify(msg) {
    if (typeof window.iprmToast === 'function') window.iprmToast(msg, 'error');
    else alert(msg);
  }

  var TYPES = [
    {type: 'heading', label: 'Заголовок', icon: 'title'},
    {type: 'paragraph', label: 'Текст', icon: 'notes'},
    {type: 'list', label: 'Список', icon: 'format_list_bulleted'},
    {type: 'quote', label: 'Цитата', icon: 'format_quote'},
    {type: 'image', label: 'Зображення', icon: 'image'},
    {type: 'gallery', label: 'Галерея', icon: 'collections'},
    {type: 'youtube', label: 'YouTube', icon: 'smart_display'},
    {type: 'callout', label: 'Виноска', icon: 'info'},
    {type: 'divider', label: 'Розділювач', icon: 'horizontal_rule'}
  ];

  window.initBlogEditor = function(opts) {
    var mount = opts.mount;
    var field = opts.field;
    if (!mount || !field) return;
    var csrfEl = document.querySelector('input[name="csrf_token"]');
    var csrf = csrfEl ? csrfEl.value : '';

    var blocks = [];  // [{type, el, getData}]

    // ---- Завантаження зображення ----
    function uploadImage(file) {
      return new Promise(function(resolve, reject) {
        var allowed = ['image/png', 'image/jpeg', 'image/webp', 'image/heic', 'image/heif'];
        var okExt = /\.(png|jpe?g|webp|heic|heif)$/i.test(file.name);
        if (allowed.indexOf(file.type) === -1 && !okExt) {
          notify('Дозволені формати: PNG, JPG, WebP, HEIC'); reject(); return;
        }
        if (file.size > 25 * 1024 * 1024) { notify('Максимальний розмір: 25 MB'); reject(); return; }
        var fd = new FormData();
        fd.append('file', file);
        fd.append('slug', opts.getSlug ? opts.getSlug() : 'post');
        if (csrf) fd.append('csrf_token', csrf);
        fetch(opts.uploadEndpoint, {method: 'POST', body: fd})
          .then(function(r) {
            if (r.status === 413) { notify('Сервер відхилив файл (413): імовірно, ліміт nginx (client_max_body_size).'); reject(); return null; }
            // Не-JSON відповідь (HTML-помилка, редірект на логін тощо) -> інформативно
            return r.json().then(function(d) { return {ok: r.ok, d: d}; }, function() {
              notify('Сервер повернув неочікувану відповідь (код ' + r.status + ')'); reject(); return null;
            });
          })
          .then(function(res) {
            if (!res) return;
            if (res.ok) resolve(res.d);
            else { notify(res.d.error || 'Помилка завантаження'); reject(); }
          })
          .catch(function() { notify('Помилка мережі'); reject(); });
      });
    }

    // ---- Інлайн rich-text (contenteditable + B/I/link) ----
    function richEditor(html) {
      var bar = el('div', {'class': 'blog-editor__inline-bar'});
      var area = el('div', {'class': 'blog-editor__rich', contenteditable: 'true'});
      area.innerHTML = html || '';
      [['format_bold', 'bold'], ['format_italic', 'italic']].forEach(function(b) {
        var btn = el('button', {type: 'button', 'class': 'blog-editor__ibtn', title: b[1]}, [icon(b[0])]);
        btn.addEventListener('mousedown', function(e) { e.preventDefault(); document.execCommand(b[1], false, null); });
        bar.appendChild(btn);
      });
      var link = el('button', {type: 'button', 'class': 'blog-editor__ibtn', title: 'Посилання'}, [icon('link')]);
      link.addEventListener('mousedown', function(e) {
        e.preventDefault();
        var url = window.prompt('URL посилання (https://...)');
        if (url) document.execCommand('createLink', false, url);
      });
      bar.appendChild(link);
      var wrap = el('div', {}, [bar, area]);
      return {wrap: wrap, getHTML: function() { return area.innerHTML.trim(); }};
    }

    // ---- Тіло блоку за типом ----
    function buildBody(type, data) {
      data = data || {};
      if (type === 'heading') {
        var sel = el('select', {'class': 'form-input blog-editor__hsel'});
        [['2', 'H2 — великий'], ['3', 'H3 — менший']].forEach(function(o) {
          var opt = el('option', {value: o[0], text: o[1]});
          if (String(data.level || 2) === o[0]) opt.selected = true;
          sel.appendChild(opt);
        });
        var inp = el('input', {'class': 'form-input', type: 'text', placeholder: 'Текст заголовка'});
        inp.value = data.text || '';
        var body = el('div', {'class': 'blog-editor__row'}, [sel, inp]);
        return {body: body, getData: function() { return {level: parseInt(sel.value, 10), text: inp.value.trim()}; }};
      }
      if (type === 'paragraph' || type === 'callout') {
        var rich = richEditor(data.html);
        var extra = null, styleSel = null;
        if (type === 'callout') {
          styleSel = el('select', {'class': 'form-input blog-editor__hsel'});
          [['info', 'Інфо'], ['warning', 'Увага'], ['success', 'Успіх']].forEach(function(o) {
            var opt = el('option', {value: o[0], text: o[1]});
            if ((data.style || 'info') === o[0]) opt.selected = true;
            styleSel.appendChild(opt);
          });
          extra = el('div', {'class': 'blog-editor__row'}, [styleSel]);
        }
        var body2 = el('div', {}, [extra, rich.wrap]);
        return {body: body2, getData: function() {
          var d = {html: rich.getHTML()};
          if (styleSel) d.style = styleSel.value;
          return d;
        }};
      }
      if (type === 'list') {
        var styleSel2 = el('select', {'class': 'form-input blog-editor__hsel'});
        [['unordered', 'Маркери'], ['ordered', 'Нумерація']].forEach(function(o) {
          var opt = el('option', {value: o[0], text: o[1]});
          if ((data.style || 'unordered') === o[0]) opt.selected = true;
          styleSel2.appendChild(opt);
        });
        var ta = el('textarea', {'class': 'form-input', rows: '4', placeholder: 'Один пункт на рядок'});
        ta.value = (data.items || []).join('\n');
        var body3 = el('div', {}, [el('div', {'class': 'blog-editor__row'}, [styleSel2]), ta]);
        return {body: body3, getData: function() {
          var items = ta.value.split('\n').map(function(s) { return s.trim(); }).filter(Boolean);
          return {style: styleSel2.value, items: items};
        }};
      }
      if (type === 'quote') {
        var qt = el('textarea', {'class': 'form-input', rows: '2', placeholder: 'Текст цитати'});
        qt.value = data.text || '';
        var cap = el('input', {'class': 'form-input', type: 'text', placeholder: 'Автор / джерело (необовʼязково)'});
        cap.value = data.caption || '';
        var body4 = el('div', {}, [qt, cap]);
        return {body: body4, getData: function() { return {text: qt.value.trim(), caption: cap.value.trim()}; }};
      }
      if (type === 'youtube') {
        var yt = el('input', {'class': 'form-input', type: 'text', placeholder: 'URL відео або 11-символьний ID'});
        yt.value = data.video_id || '';
        var ycap = el('input', {'class': 'form-input', type: 'text', placeholder: 'Підпис (необовʼязково)'});
        ycap.value = data.caption || '';
        var body5 = el('div', {}, [yt, ycap]);
        return {body: body5, getData: function() { return {video_id: yt.value.trim(), caption: ycap.value.trim()}; }};
      }
      if (type === 'image') {
        var state = {url: data.url || '', thumb: data.thumb || '', card: data.card || '',
                     media_id: data.media_id, width: data.width, height: data.height};
        var prev = el('div', {'class': 'blog-editor__img-prev'});
        function renderPrev() {
          prev.innerHTML = '';
          if (state.url) prev.appendChild(el('img', {src: state.thumb || state.url, alt: ''}));
        }
        renderPrev();
        var file = el('input', {type: 'file', accept: 'image/png,image/jpeg,image/webp,.heic,.heif', 'class': 'blog-editor__file'});
        var btn = el('button', {type: 'button', 'class': 'btn-admin btn-admin--secondary btn-admin--sm'}, [icon('upload'), 'Завантажити']);
        btn.addEventListener('click', function() { file.click(); });
        file.addEventListener('change', function() {
          if (!file.files.length) return;
          btn.disabled = true;
          uploadImage(file.files[0]).then(function(d) {
            state.url = d.url; state.thumb = d.thumb; state.card = d.card;
            state.media_id = d.media_id; state.width = d.width; state.height = d.height;
            renderPrev(); btn.disabled = false; serialize();
          }).catch(function() { btn.disabled = false; });
        });
        var alt = el('input', {'class': 'form-input', type: 'text', placeholder: 'Alt (для SEO/доступності)'});
        alt.value = data.alt || '';
        var cap2 = el('input', {'class': 'form-input', type: 'text', placeholder: 'Підпис (необовʼязково)'});
        cap2.value = data.caption || '';
        var body6 = el('div', {}, [prev, el('div', {'class': 'blog-editor__row'}, [btn]), alt, cap2, file]);
        return {body: body6, getData: function() {
          return {url: state.url, thumb: state.thumb, card: state.card, media_id: state.media_id,
                  width: state.width, height: state.height,
                  alt: alt.value.trim(), caption: cap2.value.trim()};
        }};
      }
      if (type === 'gallery') {
        var images = (data.images || []).slice();
        var grid = el('div', {'class': 'blog-editor__gallery'});
        function renderGrid() {
          grid.innerHTML = '';
          images.forEach(function(img, i) {
            var rm = el('button', {type: 'button', 'class': 'blog-editor__g-remove', title: 'Видалити'}, [icon('close')]);
            rm.addEventListener('click', function() { images.splice(i, 1); renderGrid(); serialize(); });
            grid.appendChild(el('div', {'class': 'blog-editor__g-item'}, [
              el('img', {'class': 'iprm-img-cover', src: img.thumb || img.url, alt: ''}), rm
            ]));
          });
        }
        renderGrid();
        var gfile = el('input', {type: 'file', accept: 'image/png,image/jpeg,image/webp,.heic,.heif', multiple: 'multiple', 'class': 'blog-editor__file'});
        var gbtn = el('button', {type: 'button', 'class': 'btn-admin btn-admin--secondary btn-admin--sm'}, [icon('add_photo_alternate'), 'Додати фото']);
        gbtn.addEventListener('click', function() { gfile.click(); });
        gfile.addEventListener('change', function() {
          var files = Array.prototype.slice.call(gfile.files);
          files.forEach(function(f) {
            uploadImage(f).then(function(d) {
              images.push({url: d.url, thumb: d.thumb, card: d.card, media_id: d.media_id, alt: '', caption: ''});
              renderGrid(); serialize();
            }).catch(function() {});
          });
          gfile.value = '';
        });
        var body7 = el('div', {}, [grid, el('div', {'class': 'blog-editor__row'}, [gbtn]), gfile]);
        return {body: body7, getData: function() { return {images: images}; }};
      }
      if (type === 'divider') {
        return {body: el('div', {'class': 'blog-editor__divider-prev', text: '— — —'}), getData: function() { return {}; }};
      }
      return {body: el('div'), getData: function() { return {}; }};
    }

    // ---- Обгортка блоку з контролами ----
    function makeBlock(type, data) {
      var meta = TYPES.filter(function(t) { return t.type === type; })[0] || {label: type, icon: 'widgets'};
      var built = buildBody(type, data);
      var up = el('button', {type: 'button', 'class': 'blog-editor__ctrl', title: 'Вгору'}, [icon('keyboard_arrow_up')]);
      var down = el('button', {type: 'button', 'class': 'blog-editor__ctrl', title: 'Вниз'}, [icon('keyboard_arrow_down')]);
      var del = el('button', {type: 'button', 'class': 'blog-editor__ctrl blog-editor__ctrl--danger', title: 'Видалити'}, [icon('delete')]);
      var head = el('div', {'class': 'blog-editor__bhead'}, [
        el('span', {'class': 'blog-editor__btype'}, [icon(meta.icon), document.createTextNode(' ' + meta.label)]),
        el('span', {'class': 'blog-editor__bctrls'}, [up, down, del])
      ]);
      var wrap = el('div', {'class': 'blog-editor__block', 'data-type': type, draggable: 'true'}, [head, built.body]);
      var ctrl = {type: type, el: wrap, getData: built.getData};

      function indexOf() { return blocks.indexOf(ctrl); }
      up.addEventListener('click', function() {
        var i = indexOf(); if (i > 0) { blocks.splice(i, 1); blocks.splice(i - 1, 0, ctrl); reorderDom(); }
      });
      down.addEventListener('click', function() {
        var i = indexOf(); if (i < blocks.length - 1) { blocks.splice(i, 1); blocks.splice(i + 1, 0, ctrl); reorderDom(); }
      });
      del.addEventListener('click', function() {
        var i = indexOf(); if (i > -1) { blocks.splice(i, 1); mount.removeChild(wrap); serialize(); }
      });

      // drag-reorder
      wrap.addEventListener('dragstart', function(e) { wrap.classList.add('blog-editor__block--drag'); e.dataTransfer.setData('text/plain', indexOf()); });
      wrap.addEventListener('dragend', function() { wrap.classList.remove('blog-editor__block--drag'); });
      wrap.addEventListener('dragover', function(e) { e.preventDefault(); });
      wrap.addEventListener('drop', function(e) {
        e.preventDefault();
        var from = parseInt(e.dataTransfer.getData('text/plain'), 10);
        var to = indexOf();
        if (isNaN(from) || from === to) return;
        var moved = blocks.splice(from, 1)[0];
        blocks.splice(to, 0, moved);
        reorderDom();
      });
      return ctrl;
    }

    function reorderDom() {
      blocks.forEach(function(b) { mount.appendChild(b.el); });
      serialize();
    }

    function addBlock(type, data) {
      var ctrl = makeBlock(type, data);
      blocks.push(ctrl);
      mount.appendChild(ctrl.el);
      serialize();
      return ctrl;
    }

    // ---- Панель додавання ----
    if (opts.addBar) {
      TYPES.forEach(function(t) {
        var btn = el('button', {type: 'button', 'class': 'blog-editor__addbtn'}, [icon(t.icon), document.createTextNode(' ' + t.label)]);
        btn.addEventListener('click', function() {
          var ctrl = addBlock(t.type, {});
          ctrl.el.scrollIntoView({behavior: 'smooth', block: 'center'});
        });
        opts.addBar.appendChild(btn);
      });
    }

    // ---- Ініціалізація з наявного JSON ----
    var initial = [];
    try { initial = JSON.parse(field.value || '[]'); } catch (e) { initial = []; }
    if (Array.isArray(initial)) {
      initial.forEach(function(b) { if (b && b.type) addBlock(b.type, b.data || {}); });
    }

    // ---- Серіалізація ----
    function serialize() {
      var out = [];
      blocks.forEach(function(b) {
        var d;
        try { d = b.getData(); } catch (e) { return; }  // битий блок не зриває решту
        // пропускаємо очевидно порожні блоки
        if (b.type === 'paragraph' && !(d.html || '').trim()) return;
        if (b.type === 'heading' && !(d.text || '').trim()) return;
        if (b.type === 'image' && !d.url) return;
        if (b.type === 'gallery' && !(d.images && d.images.length)) return;
        if (b.type === 'youtube' && !(d.video_id || '').trim()) return;
        if (b.type === 'list' && !(d.items && d.items.length)) return;
        if (b.type === 'quote' && !(d.text || '').trim()) return;
        if (b.type === 'callout' && !(d.html || '').trim()) return;
        out.push({type: b.type, data: d});
      });
      field.value = JSON.stringify(out);
    }

    // Тримаємо приховане поле синхронним при БУДЬ-ЯКІЙ зміні в редакторі
    // (ввід тексту в contenteditable/input/textarea, зміна select, а також
    // додавання/видалення/перестановка блоків -- через виклики serialize()
    // у відповідних обробниках). Не покладаємось лише на submit-обробник:
    // якщо submit перехопить сторонній скрипт, контент усе одно вже у полі.
    mount.addEventListener('input', serialize);
    mount.addEventListener('change', serialize);
    if (opts.form) opts.form.addEventListener('submit', serialize);

    // Початкова синхронізація (на випадок редагування наявних блоків).
    serialize();
  };
})();
