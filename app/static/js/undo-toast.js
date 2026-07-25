/* undo-toast.js -- тост "Повернути" після дії, яку можна відкотити.

   Пару даних кладе сервер (app/undo.py -> context processor -> base.html):
     <script type="application/json" id="iprm-undo-data">
       {"message": "...", "url": "/admin/...", "label": "Повернути", "csrf": "..."}

   Кнопка шле звичайний POST формою, а не fetch: після відкату сторінка має
   перемалюватись із поверненим рядком, тож повний перехід тут доречніший.

   Вантажиться ПІСЛЯ toast.js -- використовує window.iprmToast. */
(function () {
  'use strict';

  // Скільки тост із відкатом висить: помітно довше за звичайний (4.5 с),
  // бо це єдине вікно, коли помилкове видалення ще можна повернути.
  var UNDO_DURATION = 10000;

  function restore(data) {
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = data.url;
    if (data.csrf) {
      var token = document.createElement('input');
      token.type = 'hidden';
      token.name = 'csrf_token';
      token.value = data.csrf;
      form.appendChild(token);
    }
    document.body.appendChild(form);
    form.submit();
  }

  function init() {
    var node = document.getElementById('iprm-undo-data');
    if (!node || typeof window.iprmToast !== 'function') return;
    var data;
    try {
      data = JSON.parse(node.textContent || 'null');
    } catch (e) {
      return;
    }
    if (!data || !data.url || !data.message) return;

    window.iprmToast(data.message, 'success', {
      duration: UNDO_DURATION,
      action: {
        label: data.label || 'Повернути',
        onClick: function () { restore(data); },
      },
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
