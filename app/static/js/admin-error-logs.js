/* Журнал помилок: копіювання для ШІ */
(function () {
  'use strict';

  function buildReport(data) {
    var lines = [
      '=== Error Report ===',
      'Error #' + data.errorId + ' | ' + data.errorCode + ' ' + data.errorType,
      'URL: ' + (data.errorUrl || 'N/A'),
      'Method: ' + (data.errorMethod || 'GET'),
      'Time: ' + data.errorTime,
      '',
      'Message: ' + data.errorMessage
    ];
    if (data.traceback) {
      lines.push('', '--- Traceback ---', data.traceback);
    }
    return lines.join('\n');
  }

  function copyToClipboard(text) {
    if (navigator.clipboard) {
      return navigator.clipboard.writeText(text);
    }
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    return Promise.resolve();
  }

  function showFeedback(el, originalText) {
    el.textContent = 'Скопійовано!';
    el.classList.add('admin-copy-error--copied');
    el.disabled = true;
    setTimeout(function () {
      el.textContent = originalText;
      el.classList.remove('admin-copy-error--copied');
      el.disabled = false;
    }, 1500);
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.admin-copy-error');
    if (!btn || btn.disabled) return;

    e.preventDefault();
    var text = buildReport(btn.dataset);
    var original = btn.textContent.trim();
    copyToClipboard(text).then(function () {
      showFeedback(btn, original);
    });
  });

  /* Кнопка "Копіювати для ШІ" на сторінці деталей */
  var detailBtn = document.getElementById('copy-for-ai');
  if (detailBtn) {
    detailBtn.addEventListener('click', function () {
      var sections = [];
      sections.push('=== Error Report ===');

      var title = document.querySelector('.admin-hero__title');
      if (title) sections.push(title.textContent.trim());

      var time = document.querySelector('.admin-hero__subtitle');
      if (time) sections.push('Time: ' + time.textContent.trim());

      document.querySelectorAll('.form-section').forEach(function (sec) {
        var heading = sec.querySelector('.admin-form__section-title');
        if (!heading) return;
        var label = heading.textContent.trim();

        var grid = sec.querySelector('.admin-form__grid');
        if (grid) {
          sections.push('');
          grid.querySelectorAll('.form-group').forEach(function (g) {
            var lbl = g.querySelector('label');
            var val = g.querySelector('.form-input, .admin-code-block');
            if (lbl && val) {
              sections.push(lbl.textContent.trim() + ': ' + val.textContent.trim());
            }
          });
        }

        var pre = sec.querySelector('.admin-code-block');
        if (pre && !grid) {
          sections.push('', '--- ' + label + ' ---', pre.textContent.trim());
        }

        var muted = sec.querySelector('.admin-text-muted');
        if (muted) {
          sections.push(label + ': ' + muted.textContent.trim());
        }
      });

      var text = sections.join('\n');
      var original = detailBtn.textContent;
      copyToClipboard(text).then(function () {
        detailBtn.textContent = 'Скопійовано!';
        setTimeout(function () {
          detailBtn.textContent = original;
        }, 1500);
      });
    });
  }
})();
