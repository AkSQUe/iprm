/* referral-share-tools.js -- Web Share API + завантаження QR.

   [data-native-share] -- кнопка нативного share (показуємо лише коли браузер
   підтримує navigator.share). [data-qr-download] -- завантажити сусідній
   inline-SVG QR як файл. Vanilla JS, без inline. */
(function () {
  'use strict';

  // 1. Нативний share (progressive enhancement).
  if (navigator.share) {
    document.querySelectorAll('[data-native-share]').forEach(function (btn) {
      btn.hidden = false;
      btn.addEventListener('click', function () {
        navigator.share({
          title: 'ІПРМ',
          text: btn.getAttribute('data-share-text') || '',
          url: btn.getAttribute('data-share-url') || window.location.href
        }).catch(function () { /* користувач скасував -- ігноруємо */ });
      });
    });
  }

  // 2. Завантаження QR як SVG-файлу.
  document.querySelectorAll('[data-qr-download]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var wrap = btn.closest('.referral-tools__qr-wrap');
      var svg = wrap && wrap.querySelector('svg');
      if (!svg) return;
      var data = new XMLSerializer().serializeToString(svg);
      var blob = new Blob([data], { type: 'image/svg+xml;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'referral-qr.svg';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    });
  });
})();
