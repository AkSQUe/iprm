/* page-courses-schedule.js -- перемикач "Список / Календар" + інтерактивний
   календар на FullCalendar.

   Можливості:
   - Lazy-load бандла FullCalendar (тільки при першому відкритті календаря).
   - Фільтри: формат / тип заходу / лектор (чіпи) + локальний пошук за назвою.
   - Синхронізація з тег-фільтром карток (подія 'iprm:courses-tags').
   - Deep-link: вигляд і фільтри відображаються в URL (?view=&format=&...).
   - JSON-feed: майбутні події inline; минулі/архів довантажуються ледаче
     з /courses/calendar.json за видимим діапазоном.
   - Багатоденні події, кольорове кодування формату, .ics / Google Календар.

   FullCalendar підключається локально (без CDN) -> не розширюємо CSP. */
(function () {
  'use strict';

  // i18n: словник window.iprmI18n рендерить base.html; фолбек -- укр. ключ.
  var t = (window.iprmI18n && window.iprmI18n.t) || function (k) { return k; };

  var STORAGE_KEY = 'iprm:schedule-view';
  var MOBILE_MQ = '(max-width: 640px)';

  var UK_LOCALE = {
    code: 'uk',
    week: { dow: 1, doy: 7 },
    buttonText: {
      prev: t('Назад'), next: t('Вперед'), today: t('Сьогодні'),
      month: t('Місяць'), list: t('Список'),
    },
    weekText: t('Тиж'),
    allDayText: t('Весь день'),
    moreLinkText: function (n) { return t('+ще {n}', { n: n }); },
    noEventsText: t('Немає запланованих заходів'),
  };

  var FILTER_GROUPS = [
    { dim: 'format', label: t('Формат') },
    { dim: 'event_type', label: t('Тип заходу') },
    { dim: 'trainer', label: t('Лектор') },
  ];

  var FORMAT_LEGEND = [
    { fmt: 'online', label: t('Онлайн') },
    { fmt: 'offline', label: t('Офлайн') },
    { fmt: 'hybrid', label: t('Гібрид') },
  ];

  var dataEl = document.querySelector('script[data-schedule-events]');
  if (!dataEl) return;

  var rawData;
  try {
    rawData = JSON.parse(dataEl.textContent || '{}');
  } catch (e) {
    return;
  }
  var events = (rawData && rawData.events) || [];  // майбутні (inline)

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
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function pad(n) { return n < 10 ? '0' + n : String(n); }

  function nextDay(dstr) {
    var p = dstr.split('-');
    var d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    d.setUTCDate(d.getUTCDate() + 1);
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
  }

  function plural(n, one, few, many) {
    var mod10 = n % 10, mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
    return many;
  }

  var PIN_SVG = '<svg class="iprm-loc-badge__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>';
  var MONITOR_SVG = '<svg class="iprm-loc-badge__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>';

  function locationBadge(format, location) {
    if (format === 'online') {
      return '<span class="iprm-loc-badge iprm-loc-badge--online">' + MONITOR_SVG +
        '<span class="iprm-loc-badge__text">' + escapeHtml(t('Онлайн')) + '</span></span>';
    }
    if (!location) return '';
    var sub = format === 'hybrid' ? '<span class="iprm-loc-badge__sub">' + escapeHtml(t('+ онлайн')) + '</span>' : '';
    return '<span class="iprm-loc-badge iprm-loc-badge--offline">' + PIN_SVG +
      '<span class="iprm-loc-badge__text">' + escapeHtml(location) + '</span>' + sub + '</span>';
  }

  var MONTHS_GEN = [t('січня'), t('лютого'), t('березня'), t('квітня'), t('травня'), t('червня'),
    t('липня'), t('серпня'), t('вересня'), t('жовтня'), t('листопада'), t('грудня')];

  function dayLabel(dstr) {
    var p = dstr.split('-');
    return parseInt(p[2], 10) + ' ' + MONTHS_GEN[parseInt(p[1], 10) - 1];
  }

  function fullDateLabel(ev) {
    var year = ev.date.split('-')[0];
    return (ev.end && ev.end !== ev.date)
      ? dayLabel(ev.date) + ' – ' + dayLabel(ev.end) + ' ' + year
      : dayLabel(ev.date) + ' ' + year;
  }

  // ----- filtering state -------------------------------------------------
  var active = { format: {}, event_type: {}, trainer: {} };
  var tagFilter = [];     // спільний з картками (AND-матч по ev.tags)
  var searchQuery = '';   // локальний пошук календаря (за назвою)

  function valuesFor(dim) {
    var seen = {}, out = [];
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
      var sel = active[dims[i]];
      if (!Object.keys(sel).length) continue;  // AND між вимірами, OR всередині
      var val = ev[dims[i]];
      if (!val || !sel[val]) return false;
    }
    // Теги (з карток): подія має містити УСІ обрані теги.
    if (tagFilter.length) {
      var evTags = ev.tags || [];
      for (var t = 0; t < tagFilter.length; t++) {
        if (evTags.indexOf(tagFilter[t]) === -1) return false;
      }
    }
    // Пошук за назвою.
    if (searchQuery && (ev.title || '').toLowerCase().indexOf(searchQuery) === -1) {
      return false;
    }
    return true;
  }

  function anyFilterActive() {
    return Object.keys(active.format).length +
      Object.keys(active.event_type).length +
      Object.keys(active.trainer).length + tagFilter.length > 0 || !!searchQuery;
  }

  function toFcEvent(ev) {
    var classes = ['iprm-fc-ev', 'iprm-fc-ev--' + (ev.format || 'offline')];
    if (ev.past) classes.push('iprm-fc-ev--past');
    var obj = {
      id: String(ev.id),
      title: ev.title,
      start: ev.date,
      allDay: true,
      classNames: classes,
      extendedProps: { ev: ev },
    };
    if (ev.end && ev.end !== ev.date) obj.end = nextDay(ev.end);
    return obj;
  }

  // ----- event store + JSON-feed (архів) ---------------------------------
  var eventsById = {};
  events.forEach(function (ev) { eventsById[ev.id] = ev; });  // seed: майбутні
  var fetchedMonths = {};
  var feedUrl = calEl && calEl.getAttribute('data-feed-url');
  var todayMonthKey = (function () {
    var t = new Date();
    return t.getFullYear() + '-' + pad(t.getMonth() + 1);
  })();

  // Місяці 'YYYY-MM' у діапазоні [startStr, endStr) (end ексклюзивний).
  function monthsBetween(startStr, endStr) {
    var s = startStr.split('-'), e = endStr.split('-');
    var y = +s[0], m = +s[1];
    var ey = +e[0], em = +e[1], ed = +e[2];
    if (ed === 1) { em -= 1; if (em === 0) { em = 12; ey -= 1; } }  // ексклюзивний кінець
    var out = [];
    while (y < ey || (y === ey && m <= em)) {
      out.push(y + '-' + pad(m));
      m += 1; if (m > 12) { m = 1; y += 1; }
    }
    return out;
  }

  // Довантажує feed лише для поточного/минулих місяців (майбутні вже inline).
  function ensureRange(startStr, endStr) {
    if (!feedUrl) return Promise.resolve();
    var need = monthsBetween(startStr, endStr).filter(function (mk) {
      return mk <= todayMonthKey && !fetchedMonths[mk];
    });
    if (!need.length) return Promise.resolve();
    return fetch(feedUrl + '?start=' + startStr + '&end=' + endStr, {
      headers: { 'Accept': 'application/json' },
    })
      .then(function (r) { return r.ok ? r.json() : { events: [] }; })
      .then(function (data) {
        (data.events || []).forEach(function (ev) { eventsById[ev.id] = ev; });
        need.forEach(function (mk) { fetchedMonths[mk] = true; });
      })
      .catch(function () { /* мережа недоступна -> показуємо кеш */ });
  }

  function eventSource(info, success) {
    ensureRange(info.startStr.slice(0, 10), info.endStr.slice(0, 10)).then(function () {
      var all = [];
      for (var k in eventsById) {
        if (Object.prototype.hasOwnProperty.call(eventsById, k)) all.push(eventsById[k]);
      }
      success(all.filter(eventPasses).map(toFcEvent));
    }, function () { success([]); });
  }

  // ----- details panel ---------------------------------------------------
  function renderDetailsPlaceholder() {
    detailsEl.innerHTML = '<p class="iprm-calendar__details-empty">' +
      escapeHtml(t('Оберіть захід у календарі, щоб побачити деталі та зареєструватися.')) + '</p>';
  }

  function googleCalUrl(ev) {
    var start = ev.date.replace(/-/g, '');
    var end = nextDay(ev.end && ev.end !== ev.date ? ev.end : ev.date).replace(/-/g, '');
    var loc = ev.format === 'online' ? t('Онлайн') : (ev.location || '');
    var details = window.location.origin + ev.course_url;
    return 'https://calendar.google.com/calendar/render?action=TEMPLATE' +
      '&text=' + encodeURIComponent(ev.title) +
      '&dates=' + start + '/' + end +
      '&location=' + encodeURIComponent(loc) +
      '&details=' + encodeURIComponent(details);
  }

  function renderEventDetails(ev) {
    var meta = [];
    if (ev.event_type_label) meta.push(escapeHtml(ev.event_type_label));
    if (ev.cpd) meta.push(t('{n} балів БПР', { n: escapeHtml(ev.cpd) }));
    if (ev.price) meta.push(ev.price + ' ₴');
    if (ev.seats_left != null && ev.seats_left > 0) {
      meta.push(t(
        plural(ev.seats_left, 'залишилось {n} місце', 'залишилось {n} місця', 'залишилось {n} місць'),
        { n: ev.seats_left }
      ));
    }

    var actionHtml, addToCal;
    if (ev.past) {
      actionHtml = '<span class="badge badge--draft">' + escapeHtml(t('Захід завершено')) + '</span>';
      addToCal = '';
    } else {
      actionHtml = ev.is_open
        ? '<span class="apple-btn apple-btn--primary apple-btn--sm">' + escapeHtml(t('Реєстрація')) + '</span>'
        : '<span class="badge badge--draft">' + escapeHtml(t('Реєстрацію закрито')) + '</span>';
      addToCal =
        '<div class="iprm-cal-addto">' +
          '<span class="iprm-cal-addto__label">' + escapeHtml(t('Додати в календар:')) + '</span>' +
          '<a class="iprm-cal-addto__link" href="' + escapeHtml(ev.ics_url) + '">Apple / Outlook (.ics)</a>' +
          '<a class="iprm-cal-addto__link" href="' + escapeHtml(googleCalUrl(ev)) +
            '" target="_blank" rel="noopener">' + escapeHtml(t('Google Календар')) + '</a>' +
        '</div>';
    }
    var href = (!ev.past && ev.is_open) ? ev.register_url : ev.course_url;

    detailsEl.innerHTML =
      '<p class="iprm-calendar__details-empty"><strong>' + escapeHtml(fullDateLabel(ev)) + '</strong></p>' +
      '<a class="iprm-calendar__event" href="' + escapeHtml(href) + '">' +
        '<div>' +
          '<h4 class="iprm-calendar__event-title">' + escapeHtml(ev.title) + '</h4>' +
          locationBadge(ev.format, ev.location) +
          (ev.trainer ? '<div class="iprm-calendar__event-meta">' + escapeHtml(ev.trainer) + '</div>' : '') +
          (meta.length ? '<div class="iprm-calendar__event-meta">' + meta.join(' &middot; ') + '</div>' : '') +
        '</div>' +
        '<div>' + actionHtml + '</div>' +
      '</a>' + addToCal;

    // Фокус-менеджмент (a11y): переносимо фокус на панель деталей.
    detailsEl.setAttribute('tabindex', '-1');
    detailsEl.focus();
  }

  // Esc на панелі деталей -> повернутися до плейсхолдера й фокус на календар.
  if (detailsEl) {
    detailsEl.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        renderDetailsPlaceholder();
        if (calEl) {
          var firstEv = calEl.querySelector('.fc-event');
          if (firstEv) firstEv.focus();
        }
      }
    });
  }

  // ----- calendar --------------------------------------------------------
  var calendar = null;
  var fcLoading = null;

  function loadFullCalendar() {
    if (typeof FullCalendar !== 'undefined') return Promise.resolve();
    if (fcLoading) return fcLoading;
    var src = calEl && calEl.getAttribute('data-fc-src');
    if (!src) return Promise.reject(new Error('FullCalendar src missing'));
    fcLoading = new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error('FullCalendar load failed')); };
      document.head.appendChild(s);
    });
    return fcLoading;
  }

  function showCalendarFallback() {
    if (filtersEl) filtersEl.hidden = true;
    if (calEl) {
      calEl.innerHTML = '<p class="iprm-calendar__details-empty">' +
        escapeHtml(t('Не вдалося завантажити календар. Перегляньте розклад у режимі «Список».')) + '</p>';
    }
    if (detailsEl) detailsEl.innerHTML = '';
  }

  function eventTooltip(ev) {
    var parts = [ev.title, fullDateLabel(ev), ev.format_label];
    if (ev.format !== 'online' && ev.location) parts.push(ev.location);
    return parts.filter(Boolean).join(' · ');
  }

  function buildCalendar() {
    if (calendar || !calEl || typeof FullCalendar === 'undefined') return;

    var isMobile = window.matchMedia && window.matchMedia(MOBILE_MQ).matches;
    var initialDate = events.length ? events[0].date : undefined;

    calendar = new FullCalendar.Calendar(calEl, {
      locales: [UK_LOCALE],
      locale: 'uk',
      initialView: isMobile ? 'listMonth' : 'dayGridMonth',
      initialDate: initialDate,
      height: 'auto',
      firstDay: 1,
      eventInteractive: true,
      headerToolbar: {
        left: 'prev,next today',
        center: 'title',
        right: 'dayGridMonth,listMonth',
      },
      views: { listMonth: { buttonText: t('Список') } },
      displayEventTime: false,
      dayMaxEvents: 3,
      events: eventSource,
      eventDidMount: function (info) {
        var ev = info.event.extendedProps.ev;
        if (ev) info.el.setAttribute('title', eventTooltip(ev));
      },
      eventClick: function (info) {
        info.jsEvent.preventDefault();
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
    if (calendar) calendar.refetchEvents();
    renderDetailsPlaceholder();
  }

  // ----- filters UI ------------------------------------------------------
  function legendHtml() {
    var items = FORMAT_LEGEND.map(function (l) {
      return '<span class="iprm-cal-legend__item">' +
        '<span class="iprm-cal-legend__swatch iprm-fc-ev--' + l.fmt + '"></span>' +
        escapeHtml(l.label) + '</span>';
    }).join('');
    return '<div class="iprm-cal-legend" aria-hidden="true">' + items + '</div>';
  }

  function buildFilters() {
    if (!filtersEl) return;
    var groupsHtml = [];

    FILTER_GROUPS.forEach(function (g) {
      var vals = valuesFor(g.dim);
      if (vals.length < 2) return;
      var chips = vals.map(function (v) {
        var pressed = !!active[g.dim][v.value];
        return '<button type="button" class="iprm-cal-chip" data-dim="' + g.dim +
          '" data-val="' + escapeHtml(v.value) + '" aria-pressed="' + (pressed ? 'true' : 'false') + '">' +
          escapeHtml(v.label) + '</button>';
      }).join('');
      groupsHtml.push(
        '<div class="iprm-cal-filters__group">' +
          '<span class="iprm-cal-filters__label">' + escapeHtml(g.label) + '</span>' +
          '<div class="iprm-cal-filters__chips">' + chips + '</div>' +
        '</div>'
      );
    });

    var searchHtml =
      '<div class="iprm-cal-filters__group iprm-cal-filters__group--search">' +
        '<span class="iprm-cal-filters__label">' + escapeHtml(t('Пошук')) + '</span>' +
        '<input type="search" class="iprm-cal-search iprm-focus-ring" data-cal-search ' +
          'placeholder="' + escapeHtml(t('Назва заходу...')) + '" autocomplete="off" ' +
          'aria-label="' + escapeHtml(t('Пошук у календарі')) + '" ' +
          'value="' + escapeHtml(searchQuery) + '">' +
      '</div>';

    filtersEl.hidden = false;
    filtersEl.innerHTML =
      '<div class="iprm-cal-filters__bar">' + groupsHtml.join('') + searchHtml + '</div>' +
      legendHtml() +
      '<div class="iprm-cal-filters__footer">' +
        '<span class="iprm-cal-filters__count" data-cal-count></span>' +
        '<button type="button" class="iprm-cal-filters__reset" data-cal-reset hidden>' + escapeHtml(t('Скинути фільтри')) + '</button>' +
      '</div>';

    filtersEl.addEventListener('click', onFilterClick);
    var searchEl = filtersEl.querySelector('[data-cal-search]');
    if (searchEl) {
      var debounceId = null;
      searchEl.addEventListener('input', function () {
        clearTimeout(debounceId);
        debounceId = setTimeout(function () {
          searchQuery = searchEl.value.trim().toLowerCase();
          applyFilters();
        }, 120);
      });
    }
    updateFiltersUi();
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
    if (e.target.closest('[data-cal-reset]')) resetFilters();
  }

  function applyFilters() {
    refreshEvents();
    updateFiltersUi();
    writeUrlState();
  }

  function resetFilters() {
    active = { format: {}, event_type: {}, trainer: {} };
    searchQuery = '';
    if (filtersEl) {
      filtersEl.querySelectorAll('.iprm-cal-chip[aria-pressed="true"]').forEach(function (c) {
        c.setAttribute('aria-pressed', 'false');
      });
      var searchEl = filtersEl.querySelector('[data-cal-search]');
      if (searchEl) searchEl.value = '';
    }
    applyFilters();
  }

  function updateFiltersUi() {
    if (!filtersEl) return;
    var countEl = filtersEl.querySelector('[data-cal-count]');
    if (countEl) {
      var n = events.filter(eventPasses).length;
      countEl.textContent = t(plural(n, '{n} захід', '{n} заходи', '{n} заходів'), { n: n });
    }
    var resetBtn = filtersEl.querySelector('[data-cal-reset]');
    if (resetBtn) resetBtn.hidden = !anyFilterActive();
  }

  // ----- deep-link (URL state) ------------------------------------------
  function readUrlState() {
    var params = new URLSearchParams(window.location.search);
    ['format', 'event_type', 'trainer'].forEach(function (dim) {
      var key = dim === 'event_type' ? 'type' : dim;
      var raw = params.get(key);
      if (raw) raw.split(',').forEach(function (v) { if (v) active[dim][v] = true; });
    });
    var q = params.get('cq');
    if (q) searchQuery = q.toLowerCase();
    var tagRaw = params.get('tag');  // спільний з картками
    if (tagRaw) tagFilter = tagRaw.split(',').filter(Boolean);
    return params.get('view');
  }

  function writeUrlState() {
    var params = new URLSearchParams(window.location.search);
    function setMulti(key, obj) {
      var keys = Object.keys(obj);
      if (keys.length) params.set(key, keys.join(',')); else params.delete(key);
    }
    setMulti('format', active.format);
    setMulti('type', active.event_type);
    setMulti('trainer', active.trainer);
    if (searchQuery) params.set('cq', searchQuery); else params.delete('cq');
    if (currentView === 'calendar') params.set('view', 'calendar'); else params.delete('view');
    var qs = params.toString();
    var url = window.location.pathname + (qs ? '?' + qs : '') + window.location.hash;
    try { window.history.replaceState(null, '', url); } catch (e) { /* ignore */ }
  }

  // ----- sync з тег-фільтром карток -------------------------------------
  document.addEventListener('iprm:courses-tags', function (e) {
    tagFilter = (e.detail && e.detail.tags) || [];
    if (calendarInited) { refreshEvents(); updateFiltersUi(); }
  });

  // ----- toggle: Список / Календар --------------------------------------
  var calendarInited = false;
  var currentView = 'list';

  function setView(view, skipUrl) {
    if (view !== 'list' && view !== 'calendar') view = 'list';
    currentView = view;
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
        loadFullCalendar().then(buildCalendar).catch(showCalendarFallback);
      } else if (calendar) {
        calendar.updateSize();
      }
    }
    try { localStorage.setItem(STORAGE_KEY, view); } catch (e) { /* ignore */ }
    if (!skipUrl) writeUrlState();
  }

  toggleBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      setView(btn.getAttribute('data-schedule-view'));
    });
  });

  // ----- init -----------------------------------------------------------
  var urlView = readUrlState();
  var saved = null;
  try { saved = localStorage.getItem(STORAGE_KEY); } catch (e) { /* ignore */ }
  var hasUrlFilters = anyFilterActive();
  var initialView = urlView === 'calendar' || (hasUrlFilters && urlView !== 'list')
    ? 'calendar'
    : (urlView === 'list' ? 'list' : (saved === 'calendar' ? 'calendar' : 'list'));
  setView(initialView, true);
})();
