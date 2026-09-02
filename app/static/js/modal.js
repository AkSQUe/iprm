/* modal.js — відкриття/закриття модалок. Парний до modal.css.

   Розмітка декларативна: кнопка з data-modal-open="<id>" відкриває
   #<id>; будь-який елемент із data-modal-close усередині закриває його.
   Так сторінці не потрібен власний скрипт лише заради показу вікна. */
(function () {
  'use strict';

  var FOCUSABLE =
    'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), ' +
    'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  // Стек відкритих діалогів (id + елемент, з якого відкрито), а не одна
  // спільна змінна: .modal може відкрити другий .modal або .iprm-confirm
  // поверх себе (форма з підтвердженням перед сабмітом -- саме тому
  // .modal тепер нижче за z-index за .iprm-confirm). Єдина змінна на
  // close() тоді чистила б стан діалогу, що ще лишається на екрані:
  // фон розблокував би скрол дочасно, а фокус повертався б не туди.
  var stack = [];

  function open(id, trigger) {
    var el = document.getElementById(id);
    if (!el) { return; }
    stack.push({ id: id, trigger: trigger || document.activeElement });
    el.hidden = false;
    document.body.style.overflow = 'hidden';
    // Той самий FOCUSABLE, що й трап нижче -- інакше діалог лише зі
    // списком посилань (без input/select/textarea/button) не отримує
    // початкового фокусу, трап це бачить як "фокус поза host" і мовчки
    // не вмикається: клавіатурний користувач протабулює прямо крізь
    // aria-modal="true" на сторінку під ним.
    var focusable = el.querySelector(FOCUSABLE);
    if (focusable) { focusable.focus(); }
  }

  function close(id) {
    var el = document.getElementById(id);
    if (!el) { return; }
    el.hidden = true;
    // Знімаємо зі стеку саме запис ЦЬОГО діалогу (не завжди верхній):
    // data-modal-close всередині конкретного .modal мусить закрити його
    // навіть якщо стек чомусь неузгоджений.
    var idx = -1;
    for (var i = stack.length - 1; i >= 0; i -= 1) {
      if (stack[i].id === id) { idx = i; break; }
    }
    var entry = idx === -1 ? null : stack.splice(idx, 1)[0];
    // overflow повертаємо лише коли стек спорожнів: якщо під щойно
    // закритим лишається інший відкритий .modal, його фон не повинен
    // втратити блокування скролу.
    if (stack.length === 0) { document.body.style.overflow = ''; }
    // Фокус -- на елемент, що відкрив САМЕ цей діалог (а не глобальний
    // "останній тригер"): без цього клавіатурний користувач після
    // закриття другого діалогу опиняється не там, звідки той відкрився.
    var back = entry && entry.trigger;
    if (back && document.body.contains(back) && typeof back.focus === 'function') {
      back.focus();
    }
  }

  document.addEventListener('click', function (event) {
    var opener = event.target.closest('[data-modal-open]');
    if (opener) {
      open(opener.getAttribute('data-modal-open'), opener);
      return;
    }
    var closer = event.target.closest('[data-modal-close]');
    if (closer) {
      var host = closer.closest('.modal');
      if (host) { close(host.id); }
    }
  });

  document.addEventListener('keydown', function (event) {
    if (stack.length === 0) { return; }
    var top = stack[stack.length - 1];
    var host = document.getElementById(top.id);
    if (!host) { return; }

    // Обидві гілки нижче керуються верхнім .modal лише тоді, коли фокус
    // справді в ньому: якщо над ним відкрито .iprm-confirm (той самий
    // z-index-фікс, що зробив це можливим), і Tab, і Escape мусять дістатись
    // ЙОГО власного обробника в confirm-action.js, а не закрити чи
    // перехопити фокус діалогу, який під ним. Без цієї перевірки Escape,
    // натиснутий, щоб закрити лише підтвердження, закрив би заразом і
    // форму в .modal під ним, знищивши її вміст.
    if (!host.contains(document.activeElement)) { return; }

    if (event.key === 'Escape') {
      close(top.id);
      return;
    }

    if (event.key !== 'Tab') { return; }

    /* Той самий прийом, що й .iprm-confirm у confirm-action.js: Tab ходить
       по індексу серед фокусованих елементів діалогу з циклічним
       переходом через край, замість типової поведінки браузера, яка
       випустила б фокус на сторінку під оверлеєм. */
    var nodes = host.querySelectorAll(FOCUSABLE);
    if (!nodes.length) { return; }
    var i = Array.prototype.indexOf.call(nodes, document.activeElement);
    var next = event.shiftKey
      ? (i <= 0 ? nodes.length - 1 : i - 1)
      : (i === nodes.length - 1 ? 0 : i + 1);
    event.preventDefault();
    nodes[next].focus();
  });

  window.IprmModal = { open: open, close: close };
})();
