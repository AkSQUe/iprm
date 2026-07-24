/* i18n.js -- runtime-переклади для публічних JS-файлів.

   Читає словник {укр. рядок: переклад} із <script type="application/json"
   id="iprm-i18n-data"> (рендериться в base.html через js_translations() з
   app/js_strings.py) і експонує:

     window.iprmI18n.t(key, params)

   key -- точний український рядок (він же ключ каталогу Babel);
   params -- необов'язковий об'єкт для підстановки токенів {name} у рядку.
   Якщо перекладу немає -- повертається сам key (укр. fallback).

   Підключається ПЕРШИМ серед defer-скриптів у base.html, щоб словник був
   готовий до виконання решти модулів. Vanilla JS, без залежностей. */
(function () {
  'use strict';

  var dict = {};
  var node = document.getElementById('iprm-i18n-data');
  if (node) {
    try {
      var parsed = JSON.parse(node.textContent || '{}');
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        dict = parsed;
      }
    } catch (e) {
      /* некоректний JSON -- лишаємо порожній словник (укр. fallback) */
    }
  }

  function interpolate(str, params) {
    return str.replace(/\{(\w+)\}/g, function (match, name) {
      return Object.prototype.hasOwnProperty.call(params, name)
        ? String(params[name])
        : match;
    });
  }

  window.iprmI18n = {
    t: function (key, params) {
      var value = Object.prototype.hasOwnProperty.call(dict, key)
        ? dict[key]
        : key;
      if (typeof value !== 'string') value = String(key);
      return params ? interpolate(value, params) : value;
    },
  };
})();
