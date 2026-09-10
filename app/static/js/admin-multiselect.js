/* Мультиселект: чіпи й пошук поверх нативного <select multiple>.
 *
 * Прогресивне покращення: без цього скрипта сторінка лишається робочою --
 * видно звичайний мультиселект, сабміт іде тим самим ім'ям поля.
 * Джерело правди -- сам <select>: компонент лише малює його стан.
 */
(function () {
  'use strict';

  // Варіанти апострофа в назвах довідника ("здоров’я", U+2019) і в тому, що
  // хтось надрукує в пошуку з клавіатури ("здоров'я", ASCII U+0027) --
  // звід до одного символу, щоб пошук по одному варіанту знаходив назви з
  // іншим. Той самий список і той самий канонічний символ, що й у
  // normalize_name() (app/services/specialties.py) -- лише JS не читає
  // Python-константу, тож дублюється тут.
  var APOSTROPHE_VARIANTS = ['’', 'ʼ'];

  function normalize(text) {
    var value = text || '';
    APOSTROPHE_VARIANTS.forEach(function (variant) {
      value = value.split(variant).join("'");
    });
    return value.toLowerCase().trim();
  }

  function build(select) {
    var wrap = document.createElement('div');
    wrap.className = 'admin-multiselect';
    var control = document.createElement('div');
    control.className = 'admin-multiselect__control';
    var search = document.createElement('input');
    search.type = 'text';
    search.className = 'admin-multiselect__search';
    search.setAttribute('role', 'combobox');
    search.setAttribute('aria-expanded', 'false');
    search.setAttribute('aria-autocomplete', 'list');
    search.placeholder = select.dataset.multiselectPlaceholder || 'Пошук…';
    var list = document.createElement('ul');
    list.className = 'admin-multiselect__list';
    list.hidden = true;
    list.setAttribute('role', 'listbox');
    // aria-multiselectable НЕ ставимо: список показує лише НЕвибрані пункти
    // (renderList відсіює option.selected), тож кожен <li role="option">
    // завжди aria-selected="false" -- атрибут aria-multiselectable=true
    // обіцяв би скрінрідеру множинний вибір усередині ЦЬОГО списку, якого
    // тут немає (сам вибір живе на прихованому <select>).

    if (select.id) {
      // id-и поля пошуку й списку -- від select.id, щоб на сторінці з
      // кількома мультиселектами (наприклад, у майбутньому) вони не
      // збігались між компонентами.
      search.id = select.id + '-search';
      list.id = select.id + '-listbox';
      search.setAttribute('aria-controls', list.id);
    }

    control.appendChild(search);
    wrap.appendChild(control);
    wrap.appendChild(list);
    select.parentNode.insertBefore(wrap, select);
    select.hidden = true;
    select.setAttribute('tabindex', '-1');

    // <label for="..."> лишався прив'язаним до тепер прихованого select --
    // клік по підпису переставав фокусувати будь-що. Перенаправляємо for
    // на видиме поле пошуку; aria-label лишаємо -- він задає доступне ім'я
    // явно й переживе можливу відсутність <label> взагалі.
    var label = select.id && document.querySelector('label[for="' + select.id + '"]');
    if (label) {
      search.setAttribute('aria-label', label.textContent.trim());
      if (search.id) { label.setAttribute('for', search.id); }
    }

    return { wrap: wrap, control: control, search: search, list: list };
  }

  function renderChips(select, ui) {
    Array.prototype.slice.call(
      ui.control.querySelectorAll('.admin-multiselect__chip')
    ).forEach(function (chip) { chip.remove(); });

    Array.prototype.filter.call(select.options, function (option) {
      return option.selected;
    }).forEach(function (option) {
      var chip = document.createElement('span');
      chip.className = 'admin-multiselect__chip';
      chip.textContent = option.textContent.trim();
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'admin-multiselect__chip-remove';
      remove.setAttribute('aria-label', 'Прибрати ' + option.textContent.trim());
      remove.textContent = '×';
      remove.addEventListener('click', function () {
        option.selected = false;
        renderChips(select, ui);
        renderList(select, ui);
      });
      chip.appendChild(remove);
      ui.control.insertBefore(chip, ui.search);
    });
  }

  function renderList(select, ui) {
    var needle = normalize(ui.search.value);
    ui.list.textContent = '';
    // Список перебудовується щоразу -- попередній підсвічений <li> вже не
    // існує, тож посилання на нього лишати не можна.
    ui.search.removeAttribute('aria-activedescendant');
    var shown = 0;

    Array.prototype.forEach.call(select.children, function (node) {
      var options = node.tagName === 'OPTGROUP'
        ? Array.prototype.slice.call(node.children)
        : [node];
      var matching = options.filter(function (option) {
        return !option.selected && normalize(option.textContent).indexOf(needle) !== -1;
      });
      if (!matching.length) { return; }
      if (node.tagName === 'OPTGROUP') {
        var head = document.createElement('li');
        head.className = 'admin-multiselect__group';
        head.textContent = node.label;
        head.setAttribute('role', 'presentation');
        ui.list.appendChild(head);
      }
      matching.forEach(function (option) {
        var item = document.createElement('li');
        item.className = 'admin-multiselect__option';
        // id для aria-activedescendant поля пошуку (нижче, у move()).
        // Список тут показує лише НЕвибрані опції (matching відсіює
        // option.selected), тож aria-selected для них завжди чесно
        // "false" -- і саме тому цей атрибут більше НЕ використовується
        // як індикатор клавіатурної підсвітки (це робить окремий клас
        // is-active + aria-activedescendant, а не aria-selected).
        item.id = (ui.list.id || 'admin-multiselect') + '-option-' + shown;
        item.textContent = option.textContent.trim();
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', 'false');
        item.addEventListener('mousedown', function (event) {
          event.preventDefault();
          option.selected = true;
          ui.search.value = '';
          renderChips(select, ui);
          renderList(select, ui);
        });
        ui.list.appendChild(item);
        shown += 1;
      });
    });

    if (!shown) {
      var empty = document.createElement('li');
      empty.className = 'admin-multiselect__empty';
      empty.textContent = 'Нічого не знайдено';
      ui.list.appendChild(empty);
    }
  }

  function open(ui, isOpen) {
    ui.list.hidden = !isOpen;
    ui.search.setAttribute('aria-expanded', String(isOpen));
    if (!isOpen) {
      ui.search.removeAttribute('aria-activedescendant');
      // Список ховається, а <li> нікуди не дівається (renderList його не
      // перебудовує при закритті) -- клас is-active лишався б на ньому. Без
      // цього наступний Enter (до першого ArrowDown/ArrowUp) додавав чіп із
      // пункту, підсвіченого ще ДО Escape, замість надіслати форму.
      var current = active(ui);
      if (current) { current.classList.remove('is-active'); }
    }
  }

  function active(ui) {
    return ui.list.querySelector('.admin-multiselect__option.is-active');
  }

  function move(ui, delta) {
    var items = Array.prototype.slice.call(
      ui.list.querySelectorAll('.admin-multiselect__option')
    );
    if (!items.length) { return; }
    var current = items.indexOf(active(ui));
    items.forEach(function (item) { item.classList.remove('is-active'); });
    var next = items[Math.min(items.length - 1, Math.max(0, current + delta))]
      || items[0];
    next.classList.add('is-active');
    next.scrollIntoView({ block: 'nearest' });
    ui.search.setAttribute('aria-activedescendant', next.id);
  }

  function enhance(select) {
    var ui = build(select);
    renderChips(select, ui);
    renderList(select, ui);

    ui.control.addEventListener('click', function () { ui.search.focus(); });
    ui.search.addEventListener('focus', function () {
      renderList(select, ui);
      open(ui, true);
    });
    ui.search.addEventListener('input', function () {
      renderList(select, ui);
      open(ui, true);
    });
    ui.search.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown') { event.preventDefault(); move(ui, 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); move(ui, -1); }
      else if (event.key === 'Enter') {
        var item = active(ui);
        if (item) {
          event.preventDefault();
          item.dispatchEvent(new MouseEvent('mousedown'));
        }
      } else if (event.key === 'Escape') { open(ui, false); }
      else if (event.key === 'Backspace' && !ui.search.value) {
        var selected = Array.prototype.filter.call(select.options, function (option) {
          return option.selected;
        });
        if (selected.length) {
          selected[selected.length - 1].selected = false;
          renderChips(select, ui);
          renderList(select, ui);
        }
      }
    });
    document.addEventListener('click', function (event) {
      if (!ui.wrap.contains(event.target)) { open(ui, false); }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    Array.prototype.forEach.call(
      document.querySelectorAll('select[multiple][data-multiselect]'),
      enhance
    );
  });
}());
