/* admin-registrations-grouped.js -- розгортання груп у реєстрі «За заходами».

   Заголовок курсу згортає свою панель. Заголовок дати додатково тягне рядки
   учасників (data-rows-url) -- рівно один раз: повторне розгортання показує
   вже завантажене.

   Відкриті дати живуть у ?open=<id>,<id>: дія в рядку робить редірект на
   `next`, і без цього менеджер щоразу повертався б до згорнутого екрана.

   Рядок після вставки нічим не ініціалізується: admin-inline-edit,
   admin-copy-link, admin-transfer і modal слухають document через
   делегування, а меню дій -- нативний <details>. */
(function () {
  'use strict';

  var OPEN_PARAM = 'open';

  function panelOf(head) {
    var id = head.getAttribute('aria-controls');
    return id ? document.getElementById(id) : null;
  }

  function currentlyOpen() {
    var heads = document.querySelectorAll(
      '[data-instance-id][aria-expanded="true"]');
    return Array.prototype.map.call(heads, function (head) {
      return head.getAttribute('data-instance-id');
    });
  }

  function rememberOpen() {
    var ids = currentlyOpen();
    var url = new URL(window.location.href);
    if (ids.length) {
      url.searchParams.set(OPEN_PARAM, ids.join(','));
    } else {
      url.searchParams.delete(OPEN_PARAM);
    }
    window.history.replaceState({}, '', url.toString());
  }

  function load(head, panel) {
    var url = head.getAttribute('data-rows-url');
    if (!url || head.getAttribute('data-loaded') === '1') return;
    head.setAttribute('data-loaded', '1');
    panel.innerHTML = '<p class="registrations-groups__fallback">Завантаження...</p>';
    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
    }).then(function (response) {
      if (!response.ok) throw new Error(response.status);
      return response.text();
    }).then(function (html) {
      panel.innerHTML = html;
      // Іконки в субсеті без лігатур: вставлений фрагмент треба полагодити.
      if (window.msFixIcons) window.msFixIcons(panel);
    }).catch(function () {
      head.removeAttribute('data-loaded');
      panel.innerHTML = '<p class="registrations-groups__fallback">'
        + 'Не вдалося завантажити учасників. '
        + '<button type="button" class="btn-admin btn-admin--secondary btn-admin--sm" '
        + 'data-rows-retry>Спробувати ще</button></p>';
    });
  }

  function toggle(head, expand) {
    var panel = panelOf(head);
    if (!panel) return;
    head.setAttribute('aria-expanded', expand ? 'true' : 'false');
    panel.hidden = !expand;
    if (expand) load(head, panel);
    if (head.hasAttribute('data-instance-id')) rememberOpen();
  }

  document.addEventListener('click', function (event) {
    var retry = event.target.closest('[data-rows-retry]');
    if (retry) {
      var panel = retry.closest('.admin-disclosure__panel');
      var owner = panel && document.querySelector(
        '[aria-controls="' + panel.id + '"]');
      if (owner) load(owner, panel);
      return;
    }
    var head = event.target.closest('.admin-disclosure__head');
    if (!head) return;
    toggle(head, head.getAttribute('aria-expanded') !== 'true');
  });

  document.addEventListener('DOMContentLoaded', function () {
    var raw = new URLSearchParams(window.location.search).get(OPEN_PARAM);
    (raw ? raw.split(',') : []).forEach(function (id) {
      // id заходу -- завжди ціле число. Будь-що інше в ?open= прийшло з
      // чужих рук: у селекторі воно дало б SyntaxError і поховало б
      // відновлення решти панелей разом із собою.
      if (!/^\d+$/.test(id)) return;
      var head = document.querySelector('[data-instance-id="' + id + '"]');
      if (head) toggle(head, true);
    });
  });
}());
