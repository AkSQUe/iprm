/* page-courses-schedule.js -- перемикач "Список / Календар" + інтерактивний
   календар на FullCalendar з фільтрами (формат / тип заходу / лектор).

   Дані подій читаються з <script type="application/json" data-schedule-events>,
   що вмонтований у шаблон courses/list.html. FullCalendar підключається
   локально (app/static/vendor/fullcalendar/index.global.min.js) -- без CDN,
   щоб не розширювати CSP (script-src 'self'). */
(function () {
  'use strict';

  var STORAGE_KEY = 'iprm:schedule-view';

  // Українська локаль для FullCalendar. Назви місяців/днів FullCalendar бере
  // з нативного Intl за кодом 'uk'; тут лише підписи кнопок та службові рядки.
  var UK_LOCALE = {
    code: 'uk',
    week: { dow: 1, doy: 7 },  // тиждень з понеділка
    buttonText: {
      prev: 'Назад',
      next: 'Вперед',
      today: 'Сьогодні',
      month: 'Місяць',
      list: 'Список',
    },
    weekText: 'Тиж',
    allDayText: 'Весь день',
    moreLinkText: function (n) { return '+ще ' + n; },
    noEventsText: 'Немає запланованих заходів',
  };

  // Підписи груп фільтрів. Порядок визначає порядок рядків у панелі.
  var FILTER_GROUPS = [
    { dim: 'format', label: 'Формат' },
    { dim: 'event_type', label: 'Тип заходу' },
    { dim: 'trainer', label: 'Лектор' },
  ];

  var dataEl = document.querySelector('script[data-schedule-events]');
  if (!dataEl) return;

  var rawData;
  try {
    rawData = JSON.parse(dataEl.textContent || '{}');
  } catch (e) {
    return;
  }
  var events = (rawData && rawData.events) || [];

  // ----- DOM -------------------------------------------------------------
  var toggleBtns = document.querySelectorAll('[data-schedule-view]');
  var panes = {
    list: document.querySelector('[data-schedule-pane="list"]'),
    calendar: document.querySelector('[data-schedule-pane="calendar"]'),
  };
  if (!toggleBtns.length || !panes.list || !panes.calendar) return;

  var calEl = panes.calendar.querySelector('[data-calendar]');
  var filtersEl = panes.calendar.querySelector('[data-cal-filters]');
  var detailsEl = panes.calendar.querySelector('[data-calendar-details]');

  // ----- helpers ---------------------------------------------------------
  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Badge місця проведення (дзеркалить Jinja-макрос _location_badge).
  var PIN_SVG = '<svg class="iprm-loc-badge__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>';
  var MONITOR_SVG = '<svg class="iprm-loc-badge__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>';

  function locationBadge(format, location) {
    if (format === 'online') {
      return '<span class="iprm-loc-badge iprm-loc-badge--online">' + MONITOR_SVG +
        '<span class="iprm-loc-badge__text">Онлайн</span></span>';
    }
    var tbd = location ? '' : ' iprm-loc-badge--tbd';
    var text = escapeHtml(location || 'Місто уточнюється');
    var sub = format === 'hybrid' ? '<span class="iprm-loc-badge__sub">+ онлайн</span>' : '';
    return '<span class="iprm-loc-badge iprm-loc-badge--offline' + tbd + '">' + PIN_SVG +
      '<span class="iprm-loc-badge__text">' + text + '</span>' + sub + '</span>';
  }

  // ----- filtering state -------------------------------------------------
  // active[dim] = Set вибраних значень. Порожній Set = "усі" для цього виміру.
  var active = { format: {}, event_type: {}, trainer: {} };

  function valuesFor(dim) {
    // Унікальні значення виміру по всіх подіях, у порядку появи.
    // Повертає список {value, label}. Для format/event_type label беремо
    // з *_label поля події; для trainer значення = label.
    var seen = {};
    var out = [];
    events.forEach(function (ev) {
      var value, label;
      if (dim === 'format') { value = ev.format; label = ev.format_label || ev.format; }
      else if (dim === 'event_type') { value = ev.event_type; label = ev.event_type_label || ev.event_type; }
      else { value = ev.trainer; label = ev.trainer; }
      if (!value || seen[value]) return;
      seen[value] = true;
      out.push({ value: value, label: label });
    });
    return out;
  }

  function eventPasses(ev) {
    var dims = ['format', 'event_type', 'trainer'];
    for (var i = 0; i < dims.length; i++) {
      var dim = dims[i];
      var sel = active[dim];
      var keys = Object.keys(sel);
      if (!keys.length) continue;  // нічого не вибрано в цьому вимірі -> пропускаємо
      var val = ev[dim];
      if (!val || !sel[val]) return false;  // AND між вимірами, OR всередині
    }
    return true;
  }

  function anyFilterActive() {
    return Object.keys(active.format).length +
      Object.keys(active.event_type).length +
      Object.keys(active.trainer).length > 0;
  }

  // FullCalendar event-обʼєкти з відфільтрованого набору.
  function fcEvents() {
    return events.filter(eventPasses).map(function (ev) {
      return {
        id: String(ev.id),
        title: ev.title,
        start: ev.date,        // YYYY-MM-DD -> all-day (без зсуву по TZ)
        allDay: true,
        classNames: ['iprm-fc-ev', 'iprm-fc-ev--' + (ev.format || 'offline')],
        extendedProps: { ev: ev },
      };
    });
  }

  // ----- details panel ---------------------------------------------------
  function renderDetailsPlaceholder() {
    detailsEl.innerHTML = '<p class="iprm-calendar__details-empty">' +
      'Оберіть захід у календарі, щоб побачити деталі та зареєструватися.</p>';
  }

  function renderEventDetails(ev) {
    var meta = [];
    if (ev.event_type_label) meta.push(escapeHtml(ev.event_type_label));
    if (ev.cpd) meta.push(escapeHtml(ev.cpd) + ' балів БПР');
    if (ev.price) meta.push(ev.price + ' ₴');

    var dateLabel = (function () {
      var p = ev.date.split('-');
      var months = ['січня', 'лютого', 'березня', 'квітня', 'травня', 'червня',
        'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня'];
      return parseInt(p[2], 10) + ' ' + months[parseInt(p[1], 10) - 1] + ' ' + p[0];
    })();

    var actionHtml = ev.is_open
      ? '<span class="iprm-btn iprm-btn--primary iprm-btn--sm">Реєстрація</span>'
      : '<span class="badge badge--draft">Реєстрацію закрито</span>';
    var href = ev.is_open ? ev.register_url : ev.course_url;

    detailsEl.innerHTML =
      '<p class="iprm-calendar__details-empty"><strong>' + escapeHtml(dateLabel) + '</strong></p>' +
      '<a class="iprm-calendar__event" href="' + escapeHtml(href) + '">' +
        '<div>' +
          '<h4 class="iprm-calendar__event-title">' + escapeHtml(ev.title) + '</h4>' +
          locationBadge(ev.format, ev.location) +
          (ev.trainer ? '<div class="iprm-calendar__event-meta">' + escapeHtml(ev.trainer) + '</div>' : '') +
          (meta.length
            ? '<div class="iprm-calendar__event-meta">' + meta.join(' &middot; ') + '</div>'
            : '') +
        '</div>' +
        '<div>' + actionHtml + '</div>' +
      '</a>';
  }

  // ----- calendar --------------------------------------------------------
  var calendar = null;

  function buildCalendar() {
    if (calendar || !calEl || typeof FullCalendar === 'undefined') return;

    var initialDate = events.length ? events[0].date : undefined;

    calendar = new FullCalendar.Calendar(calEl, {
      locales: [UK_LOCALE],
      locale: 'uk',
      initialView: 'dayGridMonth',
      initialDate: initialDate,
      height: 'auto',
      firstDay: 1,
      headerToolbar: {
        left: 'prev,next today',
        center: 'title',
        right: 'dayGridMonth,listMonth',
      },
      views: {
        listMonth: { buttonText: 'Список' },
      },
      displayEventTime: false,
      dayMaxEvents: 3,
      events: fcEvents(),
      eventClick: function (info) {
        info.jsEvent.preventDefault();  // не йдемо за url одразу -- показуємо деталі
        var ev = info.event.extendedProps.ev;
        if (ev) renderEventDetails(ev);
        if (detailsEl && detailsEl.scrollIntoView) {
          detailsEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      },
      noEventsContent: function () { return UK_LOCALE.noEventsText; },
    });

    calendar.render();
    renderDetailsPlaceholder();
  }

  function refreshEvents() {
    if (!calendar) return;
    calendar.removeAllEvents();
    calendar.addEventSource(fcEvents());
    renderDetailsPlaceholder();
  }

  // ----- filters UI ------------------------------------------------------
  function buildFilters() {
    if (!filtersEl) return;
    var groupsHtml = [];

    FILTER_GROUPS.forEach(function (g) {
      var vals = valuesFor(g.dim);
      if (vals.length < 2) return;  // фільтр за виміром з 1 значенням безглуздий
      var chips = vals.map(function (v) {
        return '<button type="button" class="iprm-cal-chip" data-dim="' + g.dim +
          '" data-val="' + escapeHtml(v.value) + '" aria-pressed="false">' +
          escapeHtml(v.label) + '</button>';
      }).join('');
      groupsHtml.push(
        '<div class="iprm-cal-filters__group">' +
          '<span class="iprm-cal-filters__label">' + escapeHtml(g.label) + '</span>' +
          '<div class="iprm-cal-filters__chips">' + chips + '</div>' +
        '</div>'
      );
    });

    if (!groupsHtml.length) { filtersEl.hidden = true; return; }

    filtersEl.innerHTML =
      '<div class="iprm-cal-filters__bar">' + groupsHtml.join('') + '</div>' +
      '<div class="iprm-cal-filters__footer">' +
        '<span class="iprm-cal-filters__count" data-cal-count></span>' +
        '<button type="button" class="iprm-cal-filters__reset" data-cal-reset hidden>Скинути фільтри</button>' +
      '</div>';

    filtersEl.addEventListener('click', onFilterClick);
    updateCount();
  }

  function onFilterClick(e) {
    var chip = e.target.closest('.iprm-cal-chip');
    if (chip) {
      var dim = chip.getAttribute('data-dim');
      var val = chip.getAttribute('data-val');
      var pressed = chip.getAttribute('aria-pressed') === 'true';
      chip.setAttribute('aria-pressed', pressed ? 'false' : 'true');
      if (pressed) delete active[dim][val];
      else active[dim][val] = true;
      applyFilters();
      return;
    }
    if (e.target.closest('[data-cal-reset]')) {
      resetFilters();
    }
  }

  function applyFilters() {
    refreshEvents();
    updateCount();
    var resetBtn = filtersEl.querySelector('[data-cal-reset]');
    if (resetBtn) resetBtn.hidden = !anyFilterActive();
  }

  function resetFilters() {
    active = { format: {}, event_type: {}, trainer: {} };
    filtersEl.querySelectorAll('.iprm-cal-chip[aria-pressed="true"]').forEach(function (c) {
      c.setAttribute('aria-pressed', 'false');
    });
    applyFilters();
  }

  function updateCount() {
    var countEl = filtersEl ? filtersEl.querySelector('[data-cal-count]') : null;
    if (!countEl) return;
    var n = events.filter(eventPasses).length;
    var word = (n % 10 === 1 && n % 100 !== 11) ? 'захід'
      : ((n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) ? 'заходи' : 'заходів');
    countEl.textContent = n + ' ' + word;
  }

  // ----- toggle: Список / Календар --------------------------------------
  var calendarInited = false;

  function setView(view) {
    if (view !== 'list' && view !== 'calendar') view = 'list';
    toggleBtns.forEach(function (btn) {
      var isActive = btn.getAttribute('data-schedule-view') === view;
      btn.classList.toggle('iprm-schedule-toggle__btn--active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    panes.list.hidden = view !== 'list';
    panes.calendar.hidden = view !== 'calendar';

    if (view === 'calendar') {
      if (!calendarInited) {
        calendarInited = true;
        buildFilters();
        buildCalendar();
      } else if (calendar) {
        // FullCalendar рахує розміри від видимого контейнера; коли pane був
        // hidden, ширина = 0. Перерахунок після показу.
        calendar.updateSize();
      }
    }
    try { localStorage.setItem(STORAGE_KEY, view); } catch (e) { /* ignore */ }
  }

  toggleBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      setView(btn.getAttribute('data-schedule-view'));
    });
  });

  // --- init: відновити збережений view ---
  var saved = null;
  try { saved = localStorage.getItem(STORAGE_KEY); } catch (e) { /* ignore */ }
  setView(saved === 'calendar' ? 'calendar' : 'list');
})();
