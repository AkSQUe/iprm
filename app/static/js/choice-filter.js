/* choice-filter.js -- пошук над довгим списком прапорців (.choice-list).
 *
 * Прогресивне покращення: обгортка [data-choice-filter] приходить з [hidden]
 * (partials/_choice_filter.html) і з'являється лише тут; без скрипта лишається
 * звичайний список, як і раніше.
 *
 * Enter у полі не сабмітить форму: людина, що натиснула його після пошуку,
 * чекає фільтра, а не збереження напівзаповненої анкети.
 */
(function () {
  'use strict';

  // Апострофи -- той самий звід, що в admin-multiselect.js і normalize_name()
  // (app/services/specialties.py): «здоров’я» в довіднику, «здоров'я» з
  // клавіатури.
  var APOSTROPHE_VARIANTS = ['’', 'ʼ'];

  // Люди шукають професію («терапевт», «ортопед»), а в списку стоїть галузь
  // («Фізична терапія», «Травматологія та ортопедія»). Тому кожне слово
  // запиту порівнюємо лише першими STEM_LENGTH літерами: «терапевт» ->
  // «терап» знаходить «терапія», «кардіолог» -> «карді» -- «Кардіологія».
  var STEM_LENGTH = 5;

  function normalize(text) {
    var value = text || '';
    APOSTROPHE_VARIANTS.forEach(function (variant) {
      value = value.split(variant).join("'");
    });
    return value.toLowerCase().trim();
  }

  function stems(query) {
    return normalize(query)
      .split(/[\s,.;—–-]+/)
      .filter(Boolean)
      .map(function (word) { return word.slice(0, STEM_LENGTH); });
  }

  function init(box) {
    var input = box.querySelector('input');
    var list = input && document.getElementById(input.getAttribute('aria-controls'));
    if (!list) return;

    var items = Array.prototype.slice.call(list.querySelectorAll('.choice-list__item'));
    var texts = items.map(function (item) { return normalize(item.textContent); });

    var empty = document.createElement('p');
    empty.className = 'choice-list__empty';
    empty.setAttribute('role', 'status');
    empty.textContent = box.getAttribute('data-empty-text') || '';
    empty.hidden = true;
    list.appendChild(empty);

    function apply() {
      var needles = stems(input.value);
      var shown = 0;
      items.forEach(function (item, index) {
        var match = needles.every(function (needle) {
          return texts[index].indexOf(needle) !== -1;
        });
        item.hidden = !match;
        if (match) shown += 1;
      });
      empty.hidden = shown > 0;
      // Інакше після звуження список лишається прокрученим униз, і перші
      // збіги опиняються вище видимої області.
      list.scrollTop = 0;
    }

    input.addEventListener('input', apply);
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') {
        event.preventDefault();
      } else if (event.key === 'Escape' && input.value) {
        event.preventDefault();
        input.value = '';
        apply();
      }
    });

    box.hidden = false;
  }

  document.querySelectorAll('[data-choice-filter]').forEach(init);
})();
