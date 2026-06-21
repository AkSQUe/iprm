/* admin-copy-link.js -- копіювання посилання для самостійного завершення
   реєстрації учасником. Кнопка [data-completion-link] робить POST за токеном
   і копіює отриманий URL у буфер обміну (з fallback на ручне копіювання). */
(function () {
  'use strict';

  function feedback(btn, iconName) {
    var icon = btn.querySelector('.material-symbols-rounded');
    if (!icon) return;
    var prev = icon.textContent;
    icon.textContent = iconName;
    btn.classList.add('is-copied');
    setTimeout(function () {
      icon.textContent = prev;
      btn.classList.remove('is-copied');
    }, 1800);
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
    var btn = e.target.closest('[data-completion-link]');
    if (!btn) return;
    e.preventDefault();
    if (btn.dataset.busy) return;
    btn.dataset.busy = '1';

    fetch(btn.getAttribute('data-completion-link'), {
      method: 'POST',
      headers: {
        'X-CSRFToken': btn.getAttribute('data-csrf') || '',
        'Accept': 'application/json'
      },
      credentials: 'same-origin'
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok || !data.url) throw new Error(data.error || 'error');
        copyText(data.url).then(function () {
          feedback(btn, 'check');
        }).catch(function () {
          window.prompt('Скопіюйте посилання вручну:', data.url);
        });
      })
      .catch(function () {
        feedback(btn, 'error');
        window.alert('Не вдалося згенерувати посилання');
      })
      .finally(function () { delete btn.dataset.busy; });
  });

  // Надіслати посилання на завершення реєстрації листом учаснику.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-completion-email]');
    if (!btn) return;
    e.preventDefault();
    if (btn.dataset.busy) return;
    btn.dataset.busy = '1';

    fetch(btn.getAttribute('data-completion-email'), {
      method: 'POST',
      headers: {
        'X-CSRFToken': btn.getAttribute('data-csrf') || '',
        'Accept': 'application/json'
      },
      credentials: 'same-origin'
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.data.ok) throw new Error(res.data.error || 'error');
        feedback(btn, 'check');
        if (res.data.message) window.alert(res.data.message);
      })
      .catch(function (err) {
        feedback(btn, 'error');
        window.alert((err && err.message) || 'Не вдалося надіслати лист');
      })
      .finally(function () { delete btn.dataset.busy; });
  });
})();
