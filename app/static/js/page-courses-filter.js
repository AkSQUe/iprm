/* Client-side фільтр каталогу курсів.
   - Пошук за назвою (case-insensitive, з невеликим debounce).
   - AND-матриця тегів: показуємо картки з УСІМА активними тегами.
     Чіпси тегів живуть у картках і в бігучому рядку спеціальностей зверху.
   - Панель: формат / тривалість / бюджет (селекти) + сортування (перестановка
     DOM-вузлів; "за замовчуванням" відновлює порядок каталогу).
   - Усі фільтри комбінуються (логічне І). Стан віддзеркалюється в URL. */
(function () {
  var grid = document.querySelector('[data-filterable="courses"]');
  if (!grid) return;

  var cards = Array.prototype.slice.call(grid.querySelectorAll('.iprm-course-card'));
  var emptyState = grid.querySelector('[data-filter-empty]');
  var searchInput = document.querySelector('[data-course-search]');
  var resultBar = document.querySelector('[data-filter-resultbar]');
  var countEl = document.querySelector('[data-filter-count]');
  var resetBtn = document.querySelector('[data-filter-reset]');
  var marquee = document.querySelector('[data-spec-marquee]');
  var formatSel = document.querySelector('[data-filter-format]');
  var durationSel = document.querySelector('[data-filter-duration]');
  var budgetSel = document.querySelector('[data-filter-budget]');
  var sortSel = document.querySelector('[data-filter-sort]');

  var activeTags = new Set();
  var searchQuery = '';

  cards.forEach(function (card, i) {
    card.dataset.origIndex = String(i);
    var titleEl = card.querySelector('.iprm-course-card__title');
    card.dataset.searchText = (titleEl ? titleEl.textContent : '').toLowerCase();
  });

  // Deep-link: стан фільтрів у URL (?tag=a,b&q=&fmt=&dur=&budget=&sort=).
  // Тег-вимір спільний з календарем -- сповіщаємо подією 'iprm:courses-tags'.
  function writeUrl() {
    var params = new URLSearchParams(window.location.search);
    function setOrDel(key, value) {
      if (value) params.set(key, value); else params.delete(key);
    }
    setOrDel('tag', activeTags.size ? Array.from(activeTags).join(',') : '');
    setOrDel('q', searchQuery);
    setOrDel('fmt', formatSel ? formatSel.value : '');
    setOrDel('dur', durationSel ? durationSel.value : '');
    setOrDel('budget', budgetSel ? budgetSel.value : '');
    setOrDel('sort', sortSel ? sortSel.value : '');
    var qs = params.toString();
    var url = window.location.pathname + (qs ? '?' + qs : '') + window.location.hash;
    try { window.history.replaceState(null, '', url); } catch (e) { /* ignore */ }
  }

  function dispatchTags() {
    document.dispatchEvent(new CustomEvent('iprm:courses-tags', {
      detail: { tags: Array.from(activeTags) },
    }));
  }

  function pluralCourses(n) {
    var m10 = n % 10, m100 = n % 100;
    if (m100 >= 11 && m100 <= 14) return n + ' курсів';
    if (m10 === 1) return n + ' курс';
    if (m10 >= 2 && m10 <= 4) return n + ' курси';
    return n + ' курсів';
  }

  function parseJsonAttr(card, name) {
    try {
      var parsed = JSON.parse(card.getAttribute(name) || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function syncTagButtons() {
    document.querySelectorAll('.iprm-tag[data-tag-filter]').forEach(function (tag) {
      var isActive = activeTags.has(tag.getAttribute('data-tag-filter'));
      tag.classList.toggle('iprm-tag--active', isActive);
      if (tag.hasAttribute('aria-pressed')) {
        tag.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      }
    });
  }

  function matchesTags(card) {
    if (activeTags.size === 0) return true;
    var tags = parseJsonAttr(card, 'data-tags');
    var ok = true;
    activeTags.forEach(function (f) {
      if (tags.indexOf(f) === -1) ok = false;
    });
    return ok;
  }

  function matchesSearch(card) {
    if (!searchQuery) return true;
    return (card.dataset.searchText || '').indexOf(searchQuery) !== -1;
  }

  function matchesFormat(card) {
    var want = formatSel ? formatSel.value : '';
    if (!want) return true;
    return parseJsonAttr(card, 'data-formats').indexOf(want) !== -1;
  }

  function matchesDuration(card) {
    var want = durationSel ? durationSel.value : '';
    if (!want) return true;
    var days = parseInt(card.dataset.days || '', 10);
    if (isNaN(days)) return false;
    return want === '1' ? days === 1 : days >= 2;
  }

  function matchesBudget(card) {
    var want = budgetSel ? budgetSel.value : '';
    if (!want) return true;
    var price = parseInt(card.dataset.price || '', 10);
    if (isNaN(price)) return false;
    if (want === 'lt5') return price < 5000;
    if (want === '5to10') return price >= 5000 && price <= 10000;
    return price > 10000;
  }

  // Сортування: перестановка карток у grid. Порожні значення -- в кінець.
  var SORTERS = {
    'date': function (a, b) {
      return (a.dataset.date || '9999').localeCompare(b.dataset.date || '9999');
    },
    'price-asc': function (a, b) {
      return (parseInt(a.dataset.price, 10) || Infinity) - (parseInt(b.dataset.price, 10) || Infinity);
    },
    'price-desc': function (a, b) {
      return (parseInt(b.dataset.price, 10) || 0) - (parseInt(a.dataset.price, 10) || 0);
    },
    'new': function (a, b) {
      return (b.dataset.created || '').localeCompare(a.dataset.created || '');
    },
  };

  function applySort() {
    var mode = sortSel ? sortSel.value : '';
    var sorter = SORTERS[mode] || function (a, b) {
      return parseInt(a.dataset.origIndex, 10) - parseInt(b.dataset.origIndex, 10);
    };
    cards.slice().sort(sorter).forEach(function (card) {
      grid.appendChild(card);
    });
    // Empty-state завжди в кінці сітки (після перестановки карток).
    if (emptyState) grid.appendChild(emptyState);
  }

  function hasActiveFilter() {
    return activeTags.size > 0 || !!searchQuery
      || !!(formatSel && formatSel.value)
      || !!(durationSel && durationSel.value)
      || !!(budgetSel && budgetSel.value)
      || !!(sortSel && sortSel.value);
  }

  function applyFilter() {
    var visible = 0;
    cards.forEach(function (card) {
      var show = matchesTags(card) && matchesSearch(card)
        && matchesFormat(card) && matchesDuration(card) && matchesBudget(card);
      card.hidden = !show;
      if (show) visible++;
    });
    var active = hasActiveFilter();
    if (emptyState) emptyState.hidden = !active || visible > 0;

    // Result-bar з лічильником + reset показуємо лише коли є активний фільтр.
    if (resultBar) resultBar.hidden = !active;
    if (countEl && active) {
      countEl.textContent = visible > 0
        ? 'Знайдено ' + pluralCourses(visible)
        : 'Нічого не знайдено';
    }
  }

  function refresh() {
    applySort();
    applyFilter();
    writeUrl();
  }

  function resetFilters() {
    activeTags.clear();
    searchQuery = '';
    if (searchInput) searchInput.value = '';
    [formatSel, durationSel, budgetSel, sortSel].forEach(function (sel) {
      if (sel) sel.value = '';
    });
    syncTagButtons();
    refresh();
    dispatchTags();
    if (searchInput) searchInput.focus();
  }

  function toggleTag(tagName) {
    if (activeTags.has(tagName)) activeTags.delete(tagName);
    else activeTags.add(tagName);
    syncTagButtons();
    applyFilter();
    writeUrl();
    dispatchTags();
  }

  function delegateTagClicks(root) {
    if (!root) return;
    root.addEventListener('click', function (e) {
      var tag = e.target.closest('.iprm-tag[data-tag-filter]');
      if (!tag) return;
      e.preventDefault();
      toggleTag(tag.getAttribute('data-tag-filter'));
    });
  }

  delegateTagClicks(grid);
  delegateTagClicks(marquee);

  [formatSel, durationSel, budgetSel, sortSel].forEach(function (sel) {
    if (sel) sel.addEventListener('change', refresh);
  });

  if (searchInput) {
    var debounceId = null;
    searchInput.addEventListener('input', function () {
      clearTimeout(debounceId);
      debounceId = setTimeout(function () {
        searchQuery = searchInput.value.trim().toLowerCase();
        applyFilter();
        writeUrl();
      }, 120);
    });
    // Esc очищає пошук
    searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && searchInput.value) {
        searchInput.value = '';
        searchQuery = '';
        applyFilter();
        writeUrl();
      }
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', resetFilters);
  }

  // --- init: відновити стан з URL ---
  (function initFromUrl() {
    var params = new URLSearchParams(window.location.search);
    var tagRaw = params.get('tag');
    if (tagRaw) tagRaw.split(',').forEach(function (t) { if (t) activeTags.add(t); });
    var q = params.get('q');
    if (q) {
      searchQuery = q.toLowerCase();
      if (searchInput) searchInput.value = q;
    }
    function restoreSel(sel, key) {
      var v = params.get(key);
      if (sel && v && sel.querySelector('option[value="' + v + '"]')) sel.value = v;
    }
    restoreSel(formatSel, 'fmt');
    restoreSel(durationSel, 'dur');
    restoreSel(budgetSel, 'budget');
    restoreSel(sortSel, 'sort');
  })();

  syncTagButtons();
  applySort();
  applyFilter();
  dispatchTags();
})();
