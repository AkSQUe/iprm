/* admin-cert-status.js -- опитування статусу фонової генерації сертифікатів.
   Читає URL статусу з data-status-url, оновлює прогрес-бар, показує кнопку
   завантаження по завершенні. Зовнішній файл (No Inline Policy). */
(function () {
  'use strict';
  var root = document.querySelector('[data-status-url]');
  if (!root) return;
  var statusUrl = root.getAttribute('data-status-url');
  var bar = document.getElementById('cert-progress-bar');
  var text = document.getElementById('cert-progress-text');
  var doneBox = document.getElementById('cert-progress-done');
  var failBox = document.getElementById('cert-progress-failed');
  var errEl = document.getElementById('cert-error');
  var timer = null;

  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  function render(s) {
    var total = s.total || 0;
    var done = s.done || 0;
    var pct = total ? Math.round(done * 100 / total) : (s.status === 'done' ? 100 : 5);
    if (bar) bar.style.width = pct + '%';
    if (s.status === 'done') {
      if (bar) bar.style.width = '100%';
      if (text) text.textContent = 'Готово: ' + total + ' сертифікат(ів)';
      if (doneBox) doneBox.hidden = false;
      stop();
    } else if (s.status === 'failed') {
      if (text) text.textContent = 'Помилка генерації';
      if (errEl) errEl.textContent = s.error || '';
      if (failBox) failBox.hidden = false;
      stop();
    } else {
      if (text) text.textContent = 'Генерація… ' + done + ' / ' + (total || '?');
    }
  }

  function poll() {
    fetch(statusUrl, { headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) render(s); })
      .catch(function () {});
  }

  // Початкова ширина з data-pct (раніше була inline style -- No Inline Policy).
  if (bar) {
    var initPct = parseInt(bar.getAttribute('data-pct'), 10);
    if (!isNaN(initPct)) bar.style.width = initPct + '%';
  }

  poll();
  timer = setInterval(poll, 2000);
})();
