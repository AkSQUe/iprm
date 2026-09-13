/* Білдер банку питань: додавання, видалення, перенумерація полів.
 *
 * Іменування полів плоске й індексоване (question_N_text,
 * question_N_answer_M_text) -- той самий підхід, що у «блоках програми» курсу,
 * бо WTForms-репітера в цьому проєкті немає.
 *
 * ВАЖЛИВО: поля шукаються за data-role, а НЕ за типом тегу. У блоках програми
 * reindex() брав querySelector('input[type="text"]') -- там у рядку одне таке
 * поле. Тут їх п'ять (чотири варіанти + радіо), і такий підбір перейменував би
 * не те. Для радіо це особливо дорого: група з неунікальним name збиває вибір
 * правильної відповіді в сусідньому питанні.
 */
(function () {
  var container = document.getElementById('quiz-questions');
  var addBtn = document.getElementById('add-quiz-question');
  if (!container || !addBtn) return;

  var ANSWERS = 4;
  var INACTIVE_CLASS = 'admin-quiz-question--inactive';
  var counter = document.querySelector('[data-quiz-bank-count]');

  function questions() {
    return container.querySelectorAll('.admin-quiz-question');
  }

  function isInactive(item) {
    var flag = item.querySelector('[data-role="inactive"]');
    return !!(flag && flag.checked);
  }

  // Лічильник рахує лише питання в банку: виведені у спроби не йдуть, тож
  // порівнювати з «питань на спробу» треба саме їх.
  function updateCount() {
    if (!counter) return;
    var items = questions();
    var active = 0;
    for (var i = 0; i < items.length; i++) {
      if (!isInactive(items[i])) active++;
    }
    counter.textContent = active;
  }

  function reindex() {
    var items = questions();
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      item.setAttribute('data-index', i);

      var idInput = item.querySelector('[data-role="id"]');
      if (idInput) idInput.name = 'question_' + i + '_id';

      var textInput = item.querySelector('[data-role="text"]');
      if (textInput) textInput.name = 'question_' + i + '_text';

      var inactive = item.querySelector('[data-role="inactive"]');
      if (inactive) inactive.name = 'question_' + i + '_inactive';

      // Радіо: спільний name у межах питання, унікальний між питаннями.
      var radios = item.querySelectorAll('[data-role="correct"]');
      for (var r = 0; r < radios.length; r++) {
        radios[r].name = 'question_' + i + '_correct';
      }

      var answers = item.querySelectorAll('[data-role="answer"]');
      for (var a = 0; a < answers.length; a++) {
        answers[a].name = 'question_' + i + '_answer_' + a + '_text';
      }

      var number = item.querySelector('.admin-quiz-question__number');
      if (number) number.textContent = i + 1;
    }
    updateCount();
  }

  function bindRemove(item) {
    var btn = item.querySelector('.admin-quiz-question__remove');
    if (!btn) return;
    btn.addEventListener('click', function (e) {
      // Питання, що вже були у спробах, мають data-confirm. confirm-action.js
      // ловить клік раніше (capture), скасовує його і повторює лише після
      // підтвердження -- тож скасований клік тут просто пропускаємо.
      if (e.defaultPrevented) return;
      item.parentNode.removeChild(item);
      reindex();
    });
  }

  container.addEventListener('change', function (e) {
    var flag = e.target.closest('[data-role="inactive"]');
    if (!flag) return;
    var item = flag.closest('.admin-quiz-question');
    if (item) item.classList.toggle(INACTIVE_CLASS, flag.checked);
    updateCount();
  });

  function answersMarkup(idx) {
    var html = '<div class="admin-quiz-answers">';
    for (var j = 0; j < ANSWERS; j++) {
      html +=
        '<div class="admin-quiz-answer">' +
          '<label class="admin-quiz-answer__radio" title="Позначити правильною">' +
            '<input type="radio" data-role="correct" name="question_' + idx +
              '_correct" value="' + j + '"' + (j === 0 ? ' checked' : '') + '>' +
          '</label>' +
          '<input type="text" data-role="answer" class="form-input" ' +
            'name="question_' + idx + '_answer_' + j + '_text" ' +
            'placeholder="Варіант ' + (j + 1) + '">' +
        '</div>';
    }
    return html + '</div>';
  }

  addBtn.addEventListener('click', function () {
    var idx = questions().length;
    var item = document.createElement('div');
    item.className = 'admin-quiz-question';
    item.setAttribute('data-index', idx);
    item.innerHTML =
      '<input type="hidden" data-role="id" name="question_' + idx + '_id" value="">' +
      '<div class="admin-quiz-question__head">' +
        '<span class="admin-quiz-question__number">' + (idx + 1) + '</span>' +
        '<div class="admin-quiz-question__tools">' +
          '<label class="form-checkbox">' +
            '<input type="checkbox" data-role="inactive" value="1" ' +
              'name="question_' + idx + '_inactive">' +
            '<span>Виведено з банку</span>' +
          '</label>' +
          '<button type="button" class="btn-admin btn-admin--danger btn-admin--sm ' +
            'admin-quiz-question__remove">X</button>' +
        '</div>' +
      '</div>' +
      '<div class="form-group">' +
        '<label>Питання <span class="required">*</span></label>' +
        '<textarea data-role="text" name="question_' + idx + '_text" ' +
          'class="form-input" rows="2"></textarea>' +
      '</div>' +
      answersMarkup(idx) +
      '<p class="form-hint">Поля перекладу з\'являться після збереження.</p>';

    container.appendChild(item);
    bindRemove(item);
    reindex();
    var textarea = item.querySelector('[data-role="text"]');
    if (textarea) textarea.focus();
  });

  var existing = questions();
  for (var i = 0; i < existing.length; i++) bindRemove(existing[i]);
  updateCount();
})();
