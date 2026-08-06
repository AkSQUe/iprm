/* admin-promo-code.js -- дрібні помічники сторінок промокодів.
 *
 * 1) [data-promo-generate] -- підставляє випадковий код у поле. Якщо в полі
 *    вже щось є, воно стає префіксом (PHARMA -> PHARMA-A7K3XY): так пакет
 *    кодів партнера лишається впізнаваним.
 * 2) [data-copy-text] -- копіює свій текст у буфер (коди диктують і
 *    пересилають, тож ручне виділення в таблиці -- зайва морока).
 *
 * Алфавіт збігається з серверним (promo_service.CODE_ALPHABET): без 0/O та
 * 1/I/L, бо код переписують з листа й диктують телефоном.
 */
(function () {
  'use strict';

  var ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  var LENGTH = 6;

  function randomSuffix() {
    var out = '';
    var values = new Uint32Array(LENGTH);
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(values);
      for (var i = 0; i < LENGTH; i++) {
        out += ALPHABET.charAt(values[i] % ALPHABET.length);
      }
      return out;
    }
    for (var j = 0; j < LENGTH; j++) {
      out += ALPHABET.charAt(Math.floor(Math.random() * ALPHABET.length));
    }
    return out;
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        resolve();
      } catch (e) { reject(e); }
    });
  }

  document.addEventListener('click', function (e) {
    var gen = e.target.closest('[data-promo-generate]');
    if (gen) {
      e.preventDefault();
      var field = document.getElementById(gen.getAttribute('data-target') || 'promo-code');
      if (!field) return;
      var prefix = (field.value || '').trim().replace(/\s+/g, '').replace(/-+$/, '');
      field.value = prefix ? prefix + '-' + randomSuffix() : randomSuffix();
      field.focus();
      return;
    }

    var copy = e.target.closest('[data-copy-text]');
    if (copy) {
      e.preventDefault();
      var text = copy.getAttribute('data-copy-text');
      copyText(text).then(function () {
        var prev = copy.getAttribute('title') || '';
        copy.classList.add('is-copied');
        copy.setAttribute('title', 'Скопійовано');
        setTimeout(function () {
          copy.classList.remove('is-copied');
          copy.setAttribute('title', prev);
        }, 1600);
      }).catch(function () {
        window.prompt('Скопіюйте код вручну:', text);
      });
    }
  });
})();
