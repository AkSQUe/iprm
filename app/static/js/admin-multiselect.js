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

  // Поміняти місцями обраний <option> із сусіднім ОБРАНИМ у бік step.
  // Невибрані пункти пропускаємо: між двома чіпами їх у списку не видно,
  // і зупинка на них виглядала б як кнопка, що нічого не робить.
  function swapSelected(select, option, step) {
    var chosen = Array.prototype.filter.call(select.options, function (o) {
      return o.selected;
    });
    var at = chosen.indexOf(option);
    var target = chosen[at + step];
    if (!target) { return; }
    // Тільки в межах спільного батька: insertBefore на рівні <select>
    // ВИТЯГ би <option> із його <optgroup> -- групування розсипалось би
    // тихо, без жодної помилки. Сусід із іншої групи лишається на місці.
    if (option.parentNode !== target.parentNode) { return; }
    var parent = option.parentNode;
    if (step < 0) {
      parent.insertBefore(option, target);
    } else {
      parent.insertBefore(target, option);
    }
  }

  // Вибір або його порядок змінився: перемалювати компонент і сказати про це
  // сторінці. Нативний <select> шле change лише тоді, коли його чіпає
  // користувач; тут і вибір, і перестановку робить скрипт, а перестановка
  // <option> навіть не торкається .selected -- тож подію треба відтворити.
  // Інакше слухачі (прев'ю цільової аудиторії, прев'ю спікерів) про зміну не
  // дізнаються, а порядок -- це саме те, що піде на сервер при сабміті. Той
  // самий прийом, що й у admin-course-gallery.js/admin-instance-points.js.
  function sync(select, ui) {
    renderChips(select, ui);
    renderList(select, ui);
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function renderChips(select, ui) {
    Array.prototype.slice.call(
      ui.control.querySelectorAll('.admin-multiselect__chip')
    ).forEach(function (chip) { chip.remove(); });

    var ordered = select.hasAttribute('data-multiselect-ordered');
    var isFirst = true;

    Array.prototype.filter.call(select.options, function (option) {
      return option.selected;
    }).forEach(function (option) {
      var chip = document.createElement('span');
      chip.className = 'admin-multiselect__chip';
      chip.textContent = option.textContent.trim();

      // Перший обраний у впорядкованому полі -- головний лектор: його
      // підпис іде на сертифікат учасника. Рамка й жирність -- візуальний
      // маркер, title -- підказка для миші, але жодне з двох не гарантовано
      // дістається скрінрідера (title читають не всі, не завжди й не
      // одразу). Тому сенс дублюємо текстом: .visually-hidden не бачить
      // ніхто зряче, але його читає кожен скрінрідер разом з іменем чіпа.
      if (ordered && isFirst) {
        chip.classList.add('admin-multiselect__chip--primary');
        chip.title = 'Головний: його підпис іде на сертифікат учасника';
        var badge = document.createElement('span');
        badge.className = 'visually-hidden';
        badge.textContent = ' (головний, підпис на сертифікаті)';
        chip.appendChild(badge);
      }
      isFirst = false;

      // Порядок обраних <option> у DOM = порядок сабміту (браузер сам
      // гарантує це для select multiple), тож кнопки нижче рухають САМ
      // <option>, а не якийсь окремий стан -- окремого поля з індексами
      // немає й не буде.
      if (ordered) {
        // Назва змінної навмисно НЕ "move" -- у файлі вже є функція
        // move(ui, delta) для клавіатурної навігації списком; однойменна
        // локальна var усередині forEach її б не зламала (різні області
        // видимості), але читалась би як та сама сутність.
        [['◀', -1, 'Перемістити ліворуч'],
         ['▶', 1, 'Перемістити праворуч']].forEach(function (spec) {
          var moveBtn = document.createElement('button');
          moveBtn.type = 'button';
          moveBtn.className = 'admin-multiselect__chip-move';
          moveBtn.textContent = spec[0];
          moveBtn.setAttribute(
            'aria-label', spec[2] + ': ' + option.textContent.trim()
          );
          moveBtn.addEventListener('click', function () {
            swapSelected(select, option, spec[1]);
            sync(select, ui);
          });
          chip.appendChild(moveBtn);
        });
      }

      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'admin-multiselect__chip-remove';
      remove.setAttribute('aria-label', 'Прибрати ' + option.textContent.trim());
      remove.textContent = '×';
      remove.addEventListener('click', function () {
        option.selected = false;
        sync(select, ui);
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
        // data-inactive -- деактивований тренер, який лишився у choices лише
        // заради вже наявного зв'язку (див. populate_trainer_choices). Чіп
        // його показує, випадний список -- ні: новим вибором він бути не може.
        return !option.selected
          && !option.hasAttribute('data-inactive')
          && normalize(option.textContent).indexOf(needle) !== -1;
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
          // У впорядкованому полі порядок <option> -- це порядок лекторів,
          // а щойно обраний <option> лишається на своєму (алфавітному)
          // місці. Тому обраний другим міг мовчки стати першим чіпом, тобто
          // головним лектором. Переносимо в кінець: порядок кліків і є той
          // порядок, який людина мала на увазі. Опції всередині <optgroup>
          // не рухаємо -- це вивело б їх із групи.
          if (select.hasAttribute('data-multiselect-ordered')
              && option.parentNode === select) {
            select.appendChild(option);
          }
          option.selected = true;
          ui.search.value = '';
          sync(select, ui);
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
          sync(select, ui);
        }
      }
    });
    document.addEventListener('click', function (event) {
      if (!ui.wrap.contains(event.target)) { open(ui, false); }
    });

    // Вхід для чужих скриптів, що міняють вибір напряму (кнопка «Скопіювати
    // тренерів з курсу»). Слухати 'change' тут не можна: його ж шле sync(),
    // і вийшла б нескінченна рекурсія. Своя подія такої петлі не має, тож і
    // change звідси не шлемо -- це справа того, хто вибір змінив.
    select.addEventListener('admin-multiselect:refresh', function () {
      renderChips(select, ui);
      renderList(select, ui);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    Array.prototype.forEach.call(
      document.querySelectorAll('select[multiple][data-multiselect]'),
      enhance
    );
  });
}());
