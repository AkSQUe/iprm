/* Client-side фільтр каталогу курсів.
   - Пошук за назвою (case-insensitive, з невеликим debounce).
   - AND-матриця тегів: показуємо картки з УСІМА активними тегами.
   - Обидва фільтри комбінуються (логічне І): картка має пройти пошук І всі теги. */
(function () {
  var grid = document.querySelector('[data-filterable="courses"]');
  if (!grid) return;

  var cards = grid.querySelectorAll('.iprm-course-card');
  var emptyState = grid.querySelector('[data-filter-empty]');
  var searchInput = document.querySelector('[data-course-search]');
  var resultBar = document.querySelector('[data-filter-resultbar]');
  var countEl = document.querySelector('[data-filter-count]');
  var resetBtn = document.querySelector('[data-filter-reset]');

  var activeTags = new Set();
  var searchQuery = '';

  function pluralCourses(n) {
    var m10 = n % 10, m100 = n % 100;
    if (m100 >= 11 && m100 <= 14) return n + ' курсів';
    if (m10 === 1) return n + ' курс';
    if (m10 >= 2 && m10 <= 4) return n + ' курси';
    return n + ' курсів';
  }

  // Cache lowercased course titles per card (одноразово).
  cards.forEach(function (card) {
    var titleEl = card.querySelector('.iprm-course-card__title');
    card.dataset.searchText = (titleEl ? titleEl.textContent : '').toLowerCase();
  });

  function parseTags(card) {
    try {
      var raw = card.getAttribute('data-tags') || '[]';
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function syncTagButtons() {
    grid.querySelectorAll('.iprm-tag[data-tag-filter]').forEach(function (tag) {
      var isActive = activeTags.has(tag.getAttribute('data-tag-filter'));
      tag.classList.toggle('iprm-tag--active', isActive);
      tag.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
  }

  function matchesTags(card) {
    if (activeTags.size === 0) return true;
    var tags = parseTags(card);
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

  function applyFilter() {
    var visible = 0;
    cards.forEach(function (card) {
      var show = matchesTags(card) && matchesSearch(card);
      card.hidden = !show;
      if (show) visible++;
    });
    var hasActiveFilter = activeTags.size > 0 || !!searchQuery;
    if (emptyState) emptyState.hidden = !hasActiveFilter || visible > 0;

    // Result-bar з лічильником + reset показуємо лише коли є активний фільтр.
    if (resultBar) resultBar.hidden = !hasActiveFilter;
    if (countEl && hasActiveFilter) {
      countEl.textContent = visible > 0
        ? 'Знайдено ' + pluralCourses(visible)
        : 'Нічого не знайдено';
    }
  }

  function resetFilters() {
    activeTags.clear();
    searchQuery = '';
    if (searchInput) searchInput.value = '';
    syncTagButtons();
    applyFilter();
    if (searchInput) searchInput.focus();
  }

  function toggleTag(tagName) {
    if (activeTags.has(tagName)) activeTags.delete(tagName);
    else activeTags.add(tagName);
    syncTagButtons();
    applyFilter();
  }

  grid.addEventListener('click', function (e) {
    var tag = e.target.closest('.iprm-tag[data-tag-filter]');
    if (!tag) return;
    e.preventDefault();
    toggleTag(tag.getAttribute('data-tag-filter'));
  });

  if (searchInput) {
    var debounceId = null;
    searchInput.addEventListener('input', function () {
      clearTimeout(debounceId);
      debounceId = setTimeout(function () {
        searchQuery = searchInput.value.trim().toLowerCase();
        applyFilter();
      }, 120);
    });
    // Esc очищає пошук
    searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && searchInput.value) {
        searchInput.value = '';
        searchQuery = '';
        applyFilter();
      }
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', resetFilters);
  }

  syncTagButtons();
})();
