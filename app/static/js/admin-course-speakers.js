/* Прев'ю блоку спікерів у формі заходу.
 *
 * Показує, що саме збереться на сторінці заходу з карток обраних
 * тренерів, і попереджає про незаповнені -- щоб редактор не переписував
 * біографію руками і бачив дірку до збереження, а не після.
 *
 * Джерело правди -- сам <select> тренерів, як у admin-audience-preview.js:
 * слухаємо його change, а не внутрішні події компонента чіпів. Тому прев'ю
 * працює й тоді, коли мультиселект не піднявся.
 */
(function () {
  'use strict';

  var LABELS = { bio: 'немає біографії', role: 'немає ролі', photo: 'немає фото' };

  function selectedIds(select) {
    return Array.prototype.filter.call(select.options, function (option) {
      return option.selected;
    }).map(function (option) { return option.value; });
  }

  function parseIds(raw) {
    try {
      var parsed = JSON.parse(raw || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function note(box, className, text) {
    if (!text) { return; }
    var line = document.createElement('p');
    line.className = className;
    line.textContent = text;
    box.appendChild(line);
  }

  function card(data, isPrimary, isInherited) {
    var box = document.createElement('div');
    box.className = 'admin-speaker-card';
    if (isPrimary) { box.classList.add('admin-speaker-card--primary'); }
    // Успадкований склад -- не вибір цієї форми, а наслідок порожнього поля:
    // приглушена картка каже, що правити її треба в курсі, а не тут.
    if (isInherited) { box.classList.add('admin-speaker-card--inherited'); }

    if (data.photo) {
      var img = document.createElement('img');
      img.className = 'admin-speaker-card__photo';
      img.src = data.photo;
      img.alt = '';
      img.loading = 'lazy';
      box.appendChild(img);
    }

    var body = document.createElement('div');
    body.className = 'admin-speaker-card__body';

    var name = document.createElement('strong');
    name.textContent = data.full_name + (isPrimary ? ' -- головний' : '');
    body.appendChild(name);

    if (data.role) {
      var role = document.createElement('span');
      role.className = 'admin-speaker-card__role';
      role.textContent = data.role;
      body.appendChild(role);
    }
    if (data.bio) {
      var bio = document.createElement('p');
      bio.className = 'admin-speaker-card__bio';
      bio.textContent = data.bio;
      body.appendChild(bio);
    }

    if (data.missing && data.missing.length) {
      var warn = document.createElement('p');
      warn.className = 'admin-speaker-card__warning';
      // Адресно, а не «картку не заповнено»: редактор має бачити, що
      // саме йти дописувати.
      warn.textContent = 'У картці ' + data.missing.map(function (key) {
        return LABELS[key] || key;
      }).join(', ') + '. ';
      var link = document.createElement('a');
      link.href = data.edit_url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = 'Доповнити картку';
      warn.appendChild(link);
      body.appendChild(warn);
    }

    box.appendChild(body);
    return box;
  }

  function render(box, select, cache) {
    var ids = selectedIds(select);
    var inheritedIds = parseIds(box.dataset.speakersInherited);
    var isInherited = false;
    box.textContent = '';

    if (!ids.length) {
      // Порожнє поле у ФОРМІ ПРОВЕДЕННЯ означає «успадкувати склад курсу», а
      // не «без тренерів»: показуємо, кого саме буде успадковано. У формі
      // курсу успадковувати нема від кого -- там data-speakers-inherited
      // порожній, і лишається чесний порожній стан.
      if (!inheritedIds.length) {
        note(box, 'admin-speakers__empty', box.dataset.speakersEmpty);
        return;
      }
      note(box, 'admin-speakers__note', box.dataset.speakersInheritedNote);
      ids = inheritedIds.map(String);
      isInherited = true;
    }

    ids.forEach(function (id, index) {
      var slot = document.createElement('div');
      box.appendChild(slot);

      var draw = function (data) {
        slot.replaceWith(card(data, index === 0, isInherited));
      };

      if (cache[id]) { draw(cache[id]); return; }

      fetch(box.dataset.speakersUrl.replace('__ID__', id), {
        credentials: 'same-origin'
      }).then(function (response) {
        if (!response.ok) { throw new Error('card ' + response.status); }
        return response.json();
      }).then(function (data) {
        cache[id] = data;
        draw(data);
      }).catch(function () {
        // Мережа впала -- показуємо ПІБ з <option>, а не порожнє місце:
        // редактор має бачити, що тренер обраний.
        var option = select.querySelector('option[value="' + id + '"]');
        draw({
          full_name: option ? option.textContent.trim() : ('#' + id),
          role: '', bio: '', photo: '', missing: [], edit_url: '#'
        });
      });
    });
  }

  function wireCopy(button, box, select) {
    button.addEventListener('click', function () {
      var ids = parseIds(box.dataset.speakersInherited);
      if (!ids.length) { return; }
      // Саме СКОПІЮВАТИ, а не долучити: кнопка перетворює успадкування на
      // власний, зафіксований склад цієї дати, і лишити поверх нього
      // випадковий попередній вибір означало б віддати третій, ніде не
      // описаний склад.
      Array.prototype.forEach.call(select.options, function (option) {
        option.selected = false;
      });
      // Порядок курсу = порядок тренерів, тож переносимо <option> у кінець
      // по черзі: у впорядкованому полі позиція і є роллю.
      ids.forEach(function (id) {
        var option = select.querySelector('option[value="' + id + '"]');
        if (!option) { return; }
        if (option.parentNode === select) { select.appendChild(option); }
        option.selected = true;
      });
      // Перша подія перемальовує чіпи мультиселекта, друга -- прев'ю нижче
      // (воно слухає звичайний change, як і решта форми).
      select.dispatchEvent(new CustomEvent('admin-multiselect:refresh', { bubbles: true }));
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    Array.prototype.forEach.call(
      document.querySelectorAll('[data-speakers-preview]'),
      function (box) {
        var select = document.getElementById(box.dataset.speakersSource);
        if (!select) { return; }
        // Кеш на сторінку: перестановка чіпів не має ходити в мережу за
        // тим, що вже показано.
        var cache = {};
        select.addEventListener('change', function () {
          render(box, select, cache);
        });
        render(box, select, cache);

        Array.prototype.forEach.call(
          document.querySelectorAll(
            '[data-speakers-copy="' + box.dataset.speakersSource + '"]'
          ),
          function (button) { wireCopy(button, box, select); }
        );
      }
    );
  });
})();
