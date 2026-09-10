/* Пікер медіа з реєстру для редакторів. Експонує window.openMediaPicker(onPick):
   відкриває модалку, підвантажує список з /admin/media/list.json, по кліку на
   мініатюру викликає onPick(media) і закривається. Без зовнішніх залежностей. */
(function () {
  'use strict';

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'class') n.className = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var modal = document.getElementById('media-picker');
    if (!modal) return;
    var grid = document.getElementById('media-picker-grid');
    var moreBtn = document.getElementById('media-picker-more');
    var empty = document.getElementById('media-picker-empty');

    var searchEl = document.getElementById('media-picker-q');

    var onPick = null;
    var page = 1;
    var loading = false;
    var lastFocus = null;
    var term = '';

    function close() {
      modal.hidden = true;
      onPick = null;
      grid.innerHTML = '';
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    function addItems(items) {
      items.forEach(function (m) {
        var img = el('img', { 'class': 'iprm-img-cover', src: m.thumb || m.url, alt: m.alt || '', loading: 'lazy' });
        var btn = el('button', { type: 'button', 'class': 'media-picker__item', title: m.alt || ('#' + m.id) }, [img]);
        btn.addEventListener('click', function () {
          var cb = onPick;
          close();
          if (cb) cb(m);
        });
        grid.appendChild(btn);
      });
    }

    function load() {
      if (loading) return;
      loading = true;
      var url = '/admin/media/list.json?page=' + page
        + (term ? '&q=' + encodeURIComponent(term) : '');
      fetch(url, { headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          loading = false;
          if (!d) return;
          addItems(d.items || []);
          if (empty) empty.hidden = !(page === 1 && (d.items || []).length === 0);
          if (moreBtn) moreBtn.hidden = !d.has_next;
        })
        .catch(function () { loading = false; });
    }

    if (moreBtn) {
      moreBtn.addEventListener('click', function () { page += 1; load(); });
    }
    if (searchEl) {
      var timer = null;
      searchEl.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () {
          // Новий запит -- новий зріз: сторінка й уже показані мініатюри
          // від попереднього терміна до нього не належать.
          term = searchEl.value.trim();
          page = 1;
          grid.innerHTML = '';
          if (moreBtn) moreBtn.hidden = true;
          load();
        }, 300);
      });
    }
    Array.prototype.slice.call(modal.querySelectorAll('[data-picker-close]')).forEach(function (b) {
      b.addEventListener('click', close);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !modal.hidden) close();
    });

    window.openMediaPicker = function (pickCallback) {
      onPick = pickCallback;
      page = 1;
      term = '';
      if (searchEl) searchEl.value = '';
      grid.innerHTML = '';
      if (empty) empty.hidden = true;
      if (moreBtn) moreBtn.hidden = true;
      lastFocus = document.activeElement;
      modal.hidden = false;
      load();
    };
  });
})();
