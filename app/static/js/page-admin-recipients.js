/* page-admin-recipients.js — live-preview одержувачів сповіщень.

   На зміну прапорів/extra_emails у формі рулiв -- запитуємо
   /admin/notifications/recipients/preview і перерендерюємо превʼю-блок
   ПІД відповідною секцією. Сам preview-endpoint читає рівно те, що в
   БД -- тож для коректного preview після несейвнутих змін ми
   формуємо breakdown локально з form-state, не звертаючись до
   backend-у. Backend-preview залишаємо для разової синхронізації при
   завантаженні сторінки (server-side render).

   Vanilla JS, debounce 250мс. */
(function () {
  'use strict';

  var STORAGE_KEY = 'iprm-admin-recipients';
  var sections = document.querySelectorAll('[data-event-type]');
  if (!sections.length) return;

  // Global managers (snapshot з server-render — підказка про кількість)
  var managersTextarea = document.querySelector('textarea[name="manager_emails"]');

  function getManagers() {
    if (!managersTextarea) return [];
    return parseEmails(managersTextarea.value);
  }

  var EMAIL_RE = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/;

  function parseEmails(raw) {
    if (!raw) return [];
    var seen = {};
    var out = [];
    raw.replace(/,/g, '\n').split('\n').forEach(function (chunk) {
      var e = chunk.trim().toLowerCase();
      if (e && EMAIL_RE.test(e) && !seen[e]) { seen[e] = true; out.push(e); }
    });
    return out;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function renderPreview(previewEl, sources) {
    var all = sources.admins.concat(sources.managers, sources.trainer, sources.extra);
    var seen = {};
    var dedup = [];
    all.forEach(function (e) {
      if (!seen[e]) { seen[e] = true; dedup.push(e); }
    });
    if (!dedup.length) {
      previewEl.innerHTML = '<span class="recipients-preview--empty">' +
        'Нікого не охоплено – правило вимкнено або всі джерела порожні.' +
        '</span>';
      return;
    }
    var html = '<span class="recipients-preview__total">Поточних одержувачів: ' +
      dedup.length + '</span>';
    var rows = [
      ['Адміни', sources.admins],
      ['Менеджери', sources.managers],
      ['Тренер', sources.trainer],
      ['Додаткові', sources.extra],
    ];
    rows.forEach(function (r) {
      if (r[1].length) {
        html += '<br><span class="recipients-preview__source-label">' +
          escapeHtml(r[0]) + ':</span> <span class="recipients-preview__emails">' +
          escapeHtml(r[1].join(', ')) + '</span>';
      }
    });
    previewEl.innerHTML = html;
  }

  // Server-side admin list snapshot: беремо з server-rendered preview-блоків.
  // Парсимо що було там перший раз, кешуємо у пам'яті.
  var adminEmailsCache = null;
  function getAdmins(eventType) {
    if (adminEmailsCache) return adminEmailsCache;
    // Шукаємо у server-side рендері перший непорожній admins-рядок.
    var sample = null;
    sections.forEach(function (sec) {
      var emails = sec.querySelector('.recipients-preview__emails');
      if (!sample && emails && sec.querySelector('.recipients-preview__source-label') &&
          /^Адміни:/.test(sec.querySelector('.recipients-preview__source-label').textContent || '')) {
        sample = emails.textContent;
      }
    });
    adminEmailsCache = sample ? parseEmails(sample) : [];
    return adminEmailsCache;
  }

  function computeLocalSources(section) {
    var et = section.getAttribute('data-event-type');
    var prefix = 'rule__' + et + '__';
    var enabled = section.querySelector('#' + prefix + 'enabled');
    if (enabled && !enabled.checked) {
      return {admins: [], managers: [], trainer: [], extra: []};
    }

    var sources = {admins: [], managers: [], trainer: [], extra: []};
    var na = section.querySelector('#' + prefix + 'notify_admins');
    var nm = section.querySelector('#' + prefix + 'notify_managers');
    // notify_event_trainer не можемо реально резолвити без instance --
    // показуємо placeholder коли увімкнено.
    var ntr = section.querySelector('#' + prefix + 'notify_event_trainer');
    var extra = section.querySelector('#' + prefix + 'extra_emails');

    if (na && na.checked) sources.admins = getAdmins(et);
    if (nm && nm.checked) sources.managers = getManagers();
    if (ntr && ntr.checked) sources.trainer = ['(тренер заходу — з CourseInstance)'];
    if (extra) sources.extra = parseEmails(extra.value);
    return sources;
  }

  var debounce = null;
  function schedule() {
    if (debounce) window.clearTimeout(debounce);
    debounce = window.setTimeout(function () {
      sections.forEach(function (section) {
        var preview = section.querySelector('[data-recipients-preview]');
        if (!preview) return;
        renderPreview(preview, computeLocalSources(section));
      });
    }, 250);
  }

  // Listeners
  sections.forEach(function (section) {
    section.querySelectorAll('[data-recipients-toggle], [data-recipients-extra]')
      .forEach(function (el) {
        el.addEventListener('change', schedule);
        el.addEventListener('input', schedule);
      });
  });
  if (managersTextarea) {
    managersTextarea.addEventListener('input', schedule);
  }
})();
