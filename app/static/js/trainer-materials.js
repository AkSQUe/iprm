/* Заявка тренера на матеріали: прибрати рядок, додати рядок із каталогу.
   Окремо від admin-materials.js: той зав'язаний на адмінську розмітку
   (XLSX, множник, підсвітка залишків), і тут із нього не потрібне ніщо. */
(function () {
  'use strict';

  var form = document.querySelector('.trainer-materials-form');
  if (!form) { return; }

  var body = form.querySelector('[data-rows-body]');
  var search = form.querySelector('[data-catalog-search]');
  var suggest = form.querySelector('[data-suggest]');
  var catalogUrl = form.getAttribute('data-catalog-url');
  var timer = null;

  form.addEventListener('click', function (event) {
    var button = event.target.closest('[data-remove-row]');
    if (!button) { return; }
    var row = button.closest('[data-row]');
    if (row) { row.remove(); }
  });

  function hasSku(sku) {
    return Array.prototype.some.call(
      body.querySelectorAll('input[name="sku"]'),
      function (input) { return input.value === sku; }
    );
  }

  function addRow(item) {
    if (hasSku(item.sku)) { return; }

    var row = document.createElement('li');
    row.className = 'account-card trainer-materials-row';
    row.setAttribute('data-row', '');

    if (item.image_url) {
      var img = document.createElement('img');
      img.src = item.image_url;
      img.alt = '';
      img.className = 'trainer-materials-row__thumb';
      row.appendChild(img);
    }

    var name = document.createElement('span');
    name.className = 'trainer-materials-row__name';
    name.textContent = item.name || item.sku;
    row.appendChild(name);

    ['sku', 'name', 'image_url'].forEach(function (field) {
      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = field;
      hidden.value = item[field] || '';
      row.appendChild(hidden);
    });

    var qty = document.createElement('input');
    qty.type = 'number';
    qty.name = 'quantity';
    qty.className = 'form-input trainer-materials-row__qty';
    qty.min = '1';
    qty.step = '1';
    qty.value = '1';
    row.appendChild(qty);

    var remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'apple-btn apple-btn--secondary apple-btn--sm';
    remove.setAttribute('data-remove-row', '');
    remove.textContent = search.getAttribute('data-remove-label') || '×';
    row.appendChild(remove);

    body.appendChild(row);
  }

  function renderSuggestions(items) {
    suggest.innerHTML = '';
    if (!items.length) { suggest.hidden = true; return; }
    items.forEach(function (item) {
      var li = document.createElement('li');
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'apple-btn apple-btn--secondary apple-btn--sm';
      button.textContent = item.name || item.sku;
      button.addEventListener('click', function () {
        addRow(item);
        suggest.hidden = true;
        search.value = '';
      });
      li.appendChild(button);
      suggest.appendChild(li);
    });
    suggest.hidden = false;
  }

  if (search && suggest && catalogUrl) {
    search.addEventListener('input', function () {
      window.clearTimeout(timer);
      var query = search.value.trim();
      if (query.length < 2) { suggest.hidden = true; return; }
      /* Кожен запит -- живий HTTP у MM Medic, тому пауза, а не пошук на
         кожну літеру. Серверний ліміт -- 30/хв. */
      timer = window.setTimeout(function () {
        window.fetch(catalogUrl + '?q=' + encodeURIComponent(query), {
          headers: { 'Accept': 'application/json' }
        })
          .then(function (response) { return response.json(); })
          .then(function (data) { renderSuggestions(data.items || []); })
          .catch(function () { suggest.hidden = true; });
      }, 300);
    });
  }
}());
