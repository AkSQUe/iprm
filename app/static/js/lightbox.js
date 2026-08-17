/* Легкий лайтбокс для будь-яких галерей: біндиться до [data-lightbox]
   незалежно від сторінки (блог, регалії тренера, галерея курсу).
   href -- повне зображення, data-caption -- підпис. Без залежностей.
   Навігація стрілками, Esc/клік -- закрити. Стилі -- css/lightbox.css. */
(function() {
  'use strict';

  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  var links = Array.prototype.slice.call(document.querySelectorAll('[data-lightbox]'));
  if (!links.length) return;

  var overlay = document.createElement('div');
  overlay.className = 'iprm-lightbox';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', t('Перегляд зображення'));
  overlay.innerHTML =
    '<button class="iprm-lightbox__btn iprm-lightbox__close" aria-label="' + t('Закрити') + '">&times;</button>' +
    '<button class="iprm-lightbox__btn iprm-lightbox__prev" aria-label="' + t('Попереднє') + '">&#8249;</button>' +
    '<img class="iprm-lightbox__img" alt="">' +
    '<button class="iprm-lightbox__btn iprm-lightbox__next" aria-label="' + t('Наступне') + '">&#8250;</button>' +
    '<div class="iprm-lightbox__caption"></div>';
  document.body.appendChild(overlay);

  var imgEl = overlay.querySelector('.iprm-lightbox__img');
  var capEl = overlay.querySelector('.iprm-lightbox__caption');
  var closeBtn = overlay.querySelector('.iprm-lightbox__close');
  var focusable = overlay.querySelectorAll('.iprm-lightbox__btn');
  var current = -1;
  var lastFocused = null;

  function show(i) {
    if (i < 0) i = links.length - 1;
    if (i >= links.length) i = 0;
    current = i;
    var a = links[i];
    imgEl.src = a.getAttribute('href');
    imgEl.alt = (a.querySelector('img') || {}).alt || '';
    capEl.textContent = a.getAttribute('data-caption') || '';
  }
  function open(i) {
    lastFocused = document.activeElement;
    show(i);
    overlay.classList.add('iprm-lightbox--open');
    document.body.style.overflow = 'hidden';
    closeBtn.focus();  // переносимо фокус у діалог
  }
  function close() {
    overlay.classList.remove('iprm-lightbox--open');
    document.body.style.overflow = '';
    if (lastFocused && lastFocused.focus) lastFocused.focus();  // повертаємо фокус
    lastFocused = null;
  }

  links.forEach(function(a, i) {
    a.addEventListener('click', function(e) { e.preventDefault(); open(i); });
  });
  overlay.querySelector('.iprm-lightbox__close').addEventListener('click', close);
  overlay.querySelector('.iprm-lightbox__prev').addEventListener('click', function(e) { e.stopPropagation(); show(current - 1); });
  overlay.querySelector('.iprm-lightbox__next').addEventListener('click', function(e) { e.stopPropagation(); show(current + 1); });
  overlay.addEventListener('click', function(e) { if (e.target === overlay) close(); });
  document.addEventListener('keydown', function(e) {
    if (!overlay.classList.contains('iprm-lightbox--open')) return;
    if (e.key === 'Escape') { close(); }
    else if (e.key === 'ArrowLeft') { show(current - 1); }
    else if (e.key === 'ArrowRight') { show(current + 1); }
    else if (e.key === 'Tab') {
      // фокус-пастка: цикл по кнопках діалогу, не випускаємо назовні
      e.preventDefault();
      var arr = Array.prototype.slice.call(focusable);
      var idx = arr.indexOf(document.activeElement);
      var nxt = e.shiftKey ? idx - 1 : idx + 1;
      if (nxt < 0) nxt = arr.length - 1;
      if (nxt >= arr.length) nxt = 0;
      arr[nxt].focus();
    }
  });
})();
