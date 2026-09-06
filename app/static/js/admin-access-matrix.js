/* admin-access-matrix.js -- матриця прав /admin/access.

   Перемикач шле PUT одразу після кліку; при помилці повертає стан і
   пише в рядок стану. Кнопки «усе/нічого» шлють POST на модуль і
   виставляють перемикачі модуля за відповіддю. Групи згортаються,
   стан пам'ятається в localStorage. Пошук фільтрує рядки прав. */
(function () {
  'use strict';

  var root = document.getElementById('access-matrix');
  if (!root) return;

  var status = document.getElementById('access-status');
  var search = document.getElementById('access-search');
  var csrf = root.getAttribute('data-csrf') || '';
  var readonly = root.getAttribute('data-readonly') === '1';
  var STORAGE_KEY = 'admin-access-collapsed';

  function setStatus(text, state) {
    if (!status) return;
    status.textContent = text;
    status.setAttribute('data-state', state || '');
  }

  function send(url, method, payload) {
    return fetch(url, {
      method: method,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-CSRFToken': csrf,
        'X-Requested-With': 'XMLHttpRequest'
      },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
        /* Перехоплений редирект на логін (сесія збігла) повертає 200 і HTML:
           r.json() падає в catch вище, data лишається {}. Без цієї
           перевірки такий "успіх" писав би "Збережено", а гуртова дія
           знімала б усі перемикачі модуля, бо data.granted теж {}. */
        if (!data || data.ok !== true) {
          throw new Error(data && data.error ? data.error : 'Сесія завершилась, оновіть сторінку');
        }
        return data;
      });
    });
  }

  function updateCount(roleId, count) {
    var el = root.querySelector('[data-role-count="' + roleId + '"]');
    if (el) el.textContent = count + ' з ' + el.getAttribute('data-total');
  }

  /* ---- перемикачі ---- */
  root.addEventListener('change', function (e) {
    var input = e.target;
    if (readonly || !input.classList.contains('switch__input')) return;
    var granted = input.checked;
    input.disabled = true;
    setStatus('Зберігаю...', 'busy');
    send(root.getAttribute('data-api-toggle'), 'PUT', {
      role_id: Number(input.getAttribute('data-role-id')),
      permission: input.getAttribute('data-permission'),
      granted: granted
    }).then(function (data) {
      updateCount(data.role_id, data.role_count);
      setStatus('Збережено', 'ok');
    }).catch(function (err) {
      input.checked = !granted;
      setStatus('Помилка, зміну скасовано: ' + err.message, 'error');
    }).then(function () {
      input.disabled = false;
    });
  });

  /* ---- гуртові дії й згортання груп ---- */
  root.addEventListener('click', function (e) {
    var bulk = e.target.closest('[data-bulk]');
    if (bulk && !readonly) {
      var roleId = Number(bulk.getAttribute('data-role-id'));
      var module = bulk.getAttribute('data-module');
      var buttons = root.querySelectorAll('[data-bulk][data-role-id="' + roleId + '"][data-module="' + module + '"]');
      buttons.forEach(function (b) { b.disabled = true; });
      setStatus('Зберігаю...', 'busy');
      send(root.getAttribute('data-api-bulk'), 'POST', {
        role_id: roleId, module: module, mode: bulk.getAttribute('data-bulk')
      }).then(function (data) {
        var granted = data.granted || [];
        root.querySelectorAll('.switch__input[data-role-id="' + roleId + '"][data-module="' + module + '"]')
          .forEach(function (input) {
            input.checked = granted.indexOf(input.getAttribute('data-permission')) !== -1;
          });
        updateCount(data.role_id, data.role_count);
        setStatus('Збережено', 'ok');
      }).catch(function (err) {
        setStatus('Помилка: ' + err.message, 'error');
      }).then(function () {
        buttons.forEach(function (b) { b.disabled = false; });
      });
      return;
    }

    var toggle = e.target.closest('[data-group-toggle]');
    if (toggle) {
      var key = toggle.getAttribute('data-group-toggle');
      var collapsed = toggle.getAttribute('aria-expanded') === 'true';
      setCollapsed(key, collapsed);
      saveCollapsed(key, collapsed);
    }
  });

  function setCollapsed(key, collapsed) {
    var tbody = root.querySelector('.access-group[data-group="' + key + '"]');
    if (!tbody) return;
    var toggle = tbody.querySelector('[data-group-toggle]');
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    tbody.querySelectorAll('.access-module, .access-perm').forEach(function (row) {
      row.hidden = collapsed;
    });
  }

  function loadCollapsed() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
    catch (err) { return []; }
  }

  function saveCollapsed(key, collapsed) {
    var list = loadCollapsed().filter(function (k) { return k !== key; });
    if (collapsed) list.push(key);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(list)); } catch (err) { /* приватний режим */ }
  }

  loadCollapsed().forEach(function (key) { setCollapsed(key, true); });

  /* ---- пошук ---- */
  if (search) {
    search.addEventListener('input', function () {
      var q = search.value.trim().toLowerCase();
      root.querySelectorAll('.access-group').forEach(function (tbody) {
        var anyVisible = false;
        tbody.querySelectorAll('.access-module').forEach(function (moduleRow) {
          var module = moduleRow.getAttribute('data-module');
          var visible = 0;
          tbody.querySelectorAll('.access-perm .switch__input[data-module="' + module + '"]').forEach(function (input) {
            var row = input.closest('.access-perm');
            var match = !q || row.getAttribute('data-search').indexOf(q) !== -1;
            row.hidden = !match;
            if (match) visible += 1;
          });
          moduleRow.hidden = visible === 0;
          if (visible) anyVisible = true;
        });
        if (q) tbody.querySelector('[data-group-toggle]').setAttribute('aria-expanded', 'true');
        tbody.hidden = q ? !anyVisible : false;
      });
      if (!q) loadCollapsed().forEach(function (key) { setCollapsed(key, true); });
    });
  }
})();
