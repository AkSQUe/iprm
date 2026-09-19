/* Динамічний список тез пропозиції курсу (кабінет тренера).
   Прогресивне покращення: без JS працює textarea "одна теза на рядок".
   З JS textarea ховається, замість неї -- по полю на тезу з кнопками
   "+ теза" / видалити; перед сабмітом значення збираються назад у textarea. */
(function () {
  'use strict';

  var MAX = 10;

  function init(textarea) {
    var list = document.createElement('ol');
    list.className = 'trainer-theses';
    var add = document.createElement('button');
    add.type = 'button';
    add.className = 'apple-btn apple-btn--secondary apple-btn--sm';
    add.textContent = textarea.getAttribute('data-add-label') || '+';

    /* Поля створюються скриптом і не мають <label>: без aria-label
       скрінрідер озвучує лише "текстове поле". Номер перераховується при
       кожній зміні списку, бо видалення зсуває нумерацію. */
    var itemLabel = textarea.getAttribute('data-item-label') || '';
    var removeLabel = textarea.getAttribute('data-remove-label') || '-';

    function sync() {
      var values = [];
      list.querySelectorAll('li').forEach(function (li, index) {
        var input = li.querySelector('input');
        var name = (itemLabel + ' ' + (index + 1)).trim();
        input.setAttribute('aria-label', name);
        li.querySelector('button').setAttribute('aria-label', removeLabel + ': ' + name);
        if (input.value.trim()) { values.push(input.value.trim()); }
      });
      textarea.value = values.join('\n');
      add.disabled = list.children.length >= MAX;
    }

    function row(value) {
      var li = document.createElement('li');
      li.className = 'trainer-theses__row';
      var input = document.createElement('input');
      input.type = 'text';
      input.className = 'form-input';
      input.value = value || '';
      input.addEventListener('input', sync);
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'apple-btn apple-btn--secondary apple-btn--sm';
      remove.textContent = removeLabel;
      remove.addEventListener('click', function () {
        li.remove();
        if (!list.children.length) { list.appendChild(row('')); }
        sync();
      });
      li.appendChild(input);
      li.appendChild(remove);
      return li;
    }

    var initial = textarea.value.split('\n').filter(function (v) { return v.trim(); });
    (initial.length ? initial : ['']).forEach(function (v) { list.appendChild(row(v)); });

    add.addEventListener('click', function () {
      if (list.children.length < MAX) {
        var li = row('');
        list.appendChild(li);
        li.querySelector('input').focus();
        sync();
      }
    });

    textarea.hidden = true;
    textarea.insertAdjacentElement('afterend', add);
    textarea.insertAdjacentElement('afterend', list);
    if (textarea.form) { textarea.form.addEventListener('submit', sync); }
    sync();
  }

  document.querySelectorAll('textarea[data-theses]').forEach(init);
})();
