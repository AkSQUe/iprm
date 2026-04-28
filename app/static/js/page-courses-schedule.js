/* page-courses-schedule.js -- перемикач "Список / Календар" + рендер календаря.
   Дані подій читаються з <script type="application/json" data-schedule-events>
   що вмонтований у шаблон courses/list.html. */
(function () {
  'use strict';

  var STORAGE_KEY = 'iprm:schedule-view';
  var MONTH_NAMES = [
    'Січень', 'Лютий', 'Березень', 'Квітень', 'Травень', 'Червень',
    'Липень', 'Серпень', 'Вересень', 'Жовтень', 'Листопад', 'Грудень',
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
  // events групуємо по даті (YYYY-MM-DD): мапа -> [event,...]
  var eventsByDate = events.reduce(function (acc, ev) {
    if (!ev || !ev.date) return acc;
    if (!acc[ev.date]) acc[ev.date] = [];
    acc[ev.date].push(ev);
    return acc;
  }, {});

  // ----- Toggle: Список / Календар --------------------------------------
  var toggleBtns = document.querySelectorAll('[data-schedule-view]');
  var panes = {
    list: document.querySelector('[data-schedule-pane="list"]'),
    calendar: document.querySelector('[data-schedule-pane="calendar"]'),
  };
  if (!toggleBtns.length || !panes.list || !panes.calendar) return;

  function setView(view) {
    if (view !== 'list' && view !== 'calendar') view = 'list';
    toggleBtns.forEach(function (btn) {
      var isActive = btn.getAttribute('data-schedule-view') === view;
      btn.classList.toggle('iprm-schedule-toggle__btn--active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    panes.list.hidden = view !== 'list';
    panes.calendar.hidden = view !== 'calendar';
    if (view === 'calendar' && !calendarRendered) {
      calendarRendered = true;
      renderCalendar();
    }
    try { localStorage.setItem(STORAGE_KEY, view); } catch (e) { /* ignore */ }
  }

  toggleBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      setView(btn.getAttribute('data-schedule-view'));
    });
  });

  // ----- Calendar -------------------------------------------------------
  var grid = document.querySelector('[data-calendar-grid]');
  var titleEl = document.querySelector('[data-calendar-title]');
  var prevBtn = document.querySelector('[data-calendar-prev]');
  var nextBtn = document.querySelector('[data-calendar-next]');
  var detailsEl = document.querySelector('[data-calendar-details]');

  var calendarRendered = false;
  var currentYear, currentMonth;  // 0-based month
  var selectedDate = null;        // 'YYYY-MM-DD'
  var minMonth, maxMonth;         // {y, m} -- межі навігації за наявними подіями

  function pad(n) { return n < 10 ? '0' + n : String(n); }
  function ymd(y, m, d) { return y + '-' + pad(m + 1) + '-' + pad(d); }

  function computeBounds() {
    if (!events.length) return;
    var first = events[0].date.split('-');
    var last = events[events.length - 1].date.split('-');
    minMonth = { y: +first[0], m: +first[1] - 1 };
    maxMonth = { y: +last[0], m: +last[1] - 1 };
  }

  function setCurrent(y, m) {
    currentYear = y;
    currentMonth = m;
  }

  function isMonthBefore(a, b) {
    return a.y < b.y || (a.y === b.y && a.m < b.m);
  }

  function updateNavState() {
    if (!minMonth || !maxMonth) return;
    var cur = { y: currentYear, m: currentMonth };
    prevBtn.disabled = !isMonthBefore(minMonth, cur);
    nextBtn.disabled = !isMonthBefore(cur, maxMonth);
  }

  function renderGrid() {
    titleEl.textContent = MONTH_NAMES[currentMonth] + ' ' + currentYear;

    var firstDay = new Date(currentYear, currentMonth, 1);
    var lastDay = new Date(currentYear, currentMonth + 1, 0);
    // Понеділок як перший день тижня (UA): JS getDay(): Sun=0..Sat=6 -> Mon=0..Sun=6.
    var leadOffset = (firstDay.getDay() + 6) % 7;
    var daysInMonth = lastDay.getDate();
    var prevMonthDays = new Date(currentYear, currentMonth, 0).getDate();

    var todayStr = (function () {
      var t = new Date();
      return ymd(t.getFullYear(), t.getMonth(), t.getDate());
    })();

    var html = '';

    // --- "out" дні попереднього місяця (заповнюємо пустотою-паддингом) ---
    for (var i = leadOffset; i > 0; i--) {
      var d = prevMonthDays - i + 1;
      html += '<span class="iprm-calendar__day iprm-calendar__day--out" aria-hidden="true">' +
        '<span class="iprm-calendar__day-num">' + d + '</span></span>';
    }

    // --- дні поточного місяця ---
    for (var dayN = 1; dayN <= daysInMonth; dayN++) {
      var dateStr = ymd(currentYear, currentMonth, dayN);
      var hasEvent = !!eventsByDate[dateStr];
      var classes = ['iprm-calendar__day'];
      var attrs = '';
      var tag = 'span';
      if (hasEvent) {
        classes.push('iprm-calendar__day--has-event');
        tag = 'button';
        attrs = ' type="button" data-calendar-day="' + dateStr + '"';
      }
      if (dateStr === todayStr) classes.push('iprm-calendar__day--today');
      if (dateStr === selectedDate) classes.push('iprm-calendar__day--selected');

      var dotHtml = hasEvent ? '<span class="iprm-calendar__day-dot" aria-hidden="true"></span>' : '';

      html += '<' + tag + ' class="' + classes.join(' ') + '"' + attrs + '>' +
        '<span class="iprm-calendar__day-num">' + dayN + '</span>' + dotHtml +
        '</' + tag + '>';
    }

    // --- "out" дні наступного місяця, щоб дозаповнити сітку до кратного 7 ---
    var totalCells = leadOffset + daysInMonth;
    var trailing = (7 - (totalCells % 7)) % 7;
    for (var j = 1; j <= trailing; j++) {
      html += '<span class="iprm-calendar__day iprm-calendar__day--out" aria-hidden="true">' +
        '<span class="iprm-calendar__day-num">' + j + '</span></span>';
    }

    grid.innerHTML = html;
    updateNavState();
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderDetails() {
    if (!selectedDate) {
      detailsEl.innerHTML = '<p class="iprm-calendar__details-empty">' +
        'Оберіть день, виділений у календарі, щоб побачити заплановані курси.</p>';
      return;
    }
    var dayEvents = eventsByDate[selectedDate] || [];
    if (!dayEvents.length) {
      detailsEl.innerHTML = '';
      return;
    }
    var parts = [];
    var dateLabel = (function () {
      var p = selectedDate.split('-');
      return parseInt(p[2], 10) + ' ' + MONTH_NAMES[parseInt(p[1], 10) - 1].toLowerCase();
    })();
    parts.push('<p class="iprm-calendar__details-empty"><strong>' + escapeHtml(dateLabel) +
      '</strong> &middot; ' + dayEvents.length +
      (dayEvents.length === 1 ? ' захід' : ' заходи') + '</p>');

    dayEvents.forEach(function (ev) {
      var meta = [];
      if (ev.format_label) meta.push(escapeHtml(ev.format_label));
      if (ev.event_type_label) meta.push(escapeHtml(ev.event_type_label));
      if (ev.location) meta.push(escapeHtml(ev.location));
      if (ev.price) meta.push(ev.price + ' ₴');

      var actionHtml = ev.is_open
        ? '<a class="iprm-btn iprm-btn--primary iprm-btn--sm" href="' + escapeHtml(ev.register_url) + '">Реєстрація</a>'
        : '<span class="badge badge--draft">Реєстрацію закрито</span>';

      var courseUrl = ev.is_open ? ev.register_url : ev.course_url;

      parts.push(
        '<a class="iprm-calendar__event" href="' + escapeHtml(courseUrl) + '">' +
          '<div>' +
            '<h4 class="iprm-calendar__event-title">' + escapeHtml(ev.title) + '</h4>' +
            (meta.length
              ? '<div class="iprm-calendar__event-meta">' + meta.join(' &middot; ') + '</div>'
              : '') +
          '</div>' +
          '<div>' + actionHtml + '</div>' +
        '</a>'
      );
    });

    detailsEl.innerHTML = parts.join('');
  }

  function selectDate(dateStr) {
    if (!eventsByDate[dateStr]) return;
    selectedDate = dateStr;
    renderGrid();
    renderDetails();
  }

  function renderCalendar() {
    if (!grid || !titleEl || !prevBtn || !nextBtn || !detailsEl) return;
    computeBounds();

    // Стартуємо з місяця найближчої події; якщо подій немає -- з поточного.
    if (events.length) {
      var first = events[0].date.split('-');
      setCurrent(+first[0], +first[1] - 1);
      selectedDate = events[0].date;
    } else {
      var now = new Date();
      setCurrent(now.getFullYear(), now.getMonth());
      selectedDate = null;
    }

    renderGrid();
    renderDetails();
  }

  // --- nav listeners ---
  if (prevBtn) prevBtn.addEventListener('click', function () {
    var m = currentMonth - 1, y = currentYear;
    if (m < 0) { m = 11; y--; }
    setCurrent(y, m);
    renderGrid();
  });
  if (nextBtn) nextBtn.addEventListener('click', function () {
    var m = currentMonth + 1, y = currentYear;
    if (m > 11) { m = 0; y++; }
    setCurrent(y, m);
    renderGrid();
  });
  if (grid) grid.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-calendar-day]');
    if (!btn) return;
    selectDate(btn.getAttribute('data-calendar-day'));
  });

  // --- init: відновити збережений view ---
  var saved = null;
  try { saved = localStorage.getItem(STORAGE_KEY); } catch (e) { /* ignore */ }
  setView(saved === 'calendar' ? 'calendar' : 'list');
})();
