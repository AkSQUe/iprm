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

  function card(data, isPrimary) {
    var box = document.createElement('div');
    box.className = 'admin-speaker-card';
    if (isPrimary) { box.classList.add('admin-speaker-card--primary'); }

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
    box.textContent = '';

    if (!ids.length) {
      var empty = document.createElement('p');
      empty.className = 'admin-speakers__empty';
      empty.textContent = box.dataset.speakersEmpty || '';
      box.appendChild(empty);
      return;
    }

    ids.forEach(function (id, index) {
      var slot = document.createElement('div');
      box.appendChild(slot);

      var draw = function (data) {
        slot.replaceWith(card(data, index === 0));
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
      }
    );
  });
})();
