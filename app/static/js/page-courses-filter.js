/* Client-side теги-фільтри для курсів (AND-матриця: показуємо картки з УСІМА активними тегами) */
(function() {
  var grid = document.querySelector('[data-filterable="courses"]');
  if (!grid) return;

  var cards = grid.querySelectorAll('.iprm-course-card');
  var emptyState = grid.querySelector('[data-filter-empty]');
  var active = new Set();

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
    grid.querySelectorAll('.iprm-tag[data-tag-filter]').forEach(function(tag) {
      var isActive = active.has(tag.getAttribute('data-tag-filter'));
      tag.classList.toggle('iprm-tag--active', isActive);
      tag.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
  }

  function applyFilter() {
    var visibleCount = 0;
    var filters = Array.from(active);
    cards.forEach(function(card) {
      var show;
      if (filters.length === 0) {
        show = true;
      } else {
        var tags = parseTags(card);
        show = filters.every(function(f) { return tags.indexOf(f) !== -1; });
      }
      card.hidden = !show;
      if (show) visibleCount++;
    });
    if (emptyState) emptyState.hidden = visibleCount > 0 || filters.length === 0;
  }

  function toggle(tagName) {
    if (active.has(tagName)) {
      active.delete(tagName);
    } else {
      active.add(tagName);
    }
    syncTagButtons();
    applyFilter();
  }

  grid.addEventListener('click', function(e) {
    var tag = e.target.closest('.iprm-tag[data-tag-filter]');
    if (!tag) return;
    e.preventDefault();
    e.stopPropagation();
    toggle(tag.getAttribute('data-tag-filter'));
  });

  grid.addEventListener('keydown', function(e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var tag = e.target.closest('.iprm-tag[data-tag-filter]');
    if (!tag) return;
    e.preventDefault();
    e.stopPropagation();
    toggle(tag.getAttribute('data-tag-filter'));
  });

  syncTagButtons();
})();
