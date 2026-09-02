/* admin-transfer.js — заповнення модалки перенесення.

   Скрипт нічого не рахує: суми й різниці приходять з
   /admin/registrations/<id>/transfer/options уже порахованими на сервері.
   Інакше сума в модалці й сума в листі одного дня розійдуться. */
(function () {
  'use strict';

  var form = document.getElementById('transfer-form');
  if (!form) { return; }

  var instanceSelect = document.getElementById('transfer-instance');
  var tariffGroup = document.getElementById('transfer-tariff-group');
  var tariffSelect = document.getElementById('transfer-tariff');
  var initiatorSelect = document.getElementById('transfer-initiator');
  var initiatorHint = document.getElementById('transfer-initiator-hint');
  var decisionSelect = document.getElementById('transfer-decision');
  var differenceHint = document.getElementById('transfer-difference');
  var problemsBox = document.getElementById('transfer-problems');
  var submitBtn = document.getElementById('transfer-submit');
  var template = form.getAttribute('data-options-url-template');
  var data = null;

  function optionsUrl(regId) {
    return template.replace(/\/0\//, '/' + regId + '/');
  }

  function currentInstance() {
    if (!data) { return null; }
    var id = parseInt(instanceSelect.value, 10);
    for (var i = 0; i < data.instances.length; i += 1) {
      if (data.instances[i].id === id) { return data.instances[i]; }
    }
    return null;
  }

  function difference() {
    var instance = currentInstance();
    if (!instance) { return null; }
    if (instance.tariffs.length && tariffSelect.value) {
      var id = parseInt(tariffSelect.value, 10);
      for (var i = 0; i < instance.tariffs.length; i += 1) {
        if (instance.tariffs[i].id === id) {
          return instance.tariffs[i].difference;
        }
      }
    }
    return instance.difference;
  }

  function renderTariffs() {
    var instance = currentInstance();
    tariffSelect.innerHTML = '';
    if (!instance || !instance.tariffs.length) {
      tariffGroup.hidden = true;
      return;
    }
    tariffGroup.hidden = false;
    instance.tariffs.forEach(function (tariff) {
      var option = document.createElement('option');
      option.value = tariff.id;
      option.textContent = tariff.name + ' — ' + tariff.price + ' грн';
      tariffSelect.appendChild(option);
    });
  }

  function renderDifference() {
    var diff = difference();
    if (diff === null) { differenceHint.textContent = ''; return; }
    if (diff === 0) {
      differenceHint.textContent = 'Тариф збігається зі сплаченою сумою.';
    } else if (diff > 0) {
      differenceHint.textContent = 'Новий тариф дорожчий на ' + diff + ' грн.';
    } else {
      differenceHint.textContent = 'Новий тариф дешевший на ' + Math.abs(diff) + ' грн.';
    }
  }

  function renderInitiator() {
    /* §3.2 Політики: перенесення з нашої ініціативи -- без доплати.
       Вимикаємо варіант і кажемо чому, а не даємо серверу відбити мовчки. */
    var byOrganizer = initiatorSelect.value === 'organizer';
    var surcharge = decisionSelect.querySelector('option[value="surcharge"]');
    surcharge.disabled = byOrganizer;
    if (byOrganizer) {
      if (decisionSelect.value === 'surcharge') { decisionSelect.value = 'keep'; }
      initiatorHint.textContent =
        'За §3.2 Політики учасник бере участь у нову дату без додаткової '
        + 'оплати, а при відмові отримує 100% повернення.';
    } else {
      initiatorHint.textContent =
        'Повернення рахується за сіткою §4.1 від дати заявки.';
    }
  }

  function renderProblems(problems) {
    if (!problems.length) {
      problemsBox.hidden = true;
      submitBtn.disabled = false;
      return;
    }
    problemsBox.hidden = false;
    problemsBox.innerHTML = '';
    problems.forEach(function (text) {
      var line = document.createElement('div');
      line.className = 'form-error';
      line.textContent = text;
      problemsBox.appendChild(line);
    });
    submitBtn.disabled = true;
  }

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('[data-transfer-reg]');
    if (!trigger) { return; }
    var regId = trigger.getAttribute('data-transfer-reg');
    form.action = trigger.getAttribute('data-transfer-action');
    instanceSelect.innerHTML = '';
    problemsBox.hidden = true;
    submitBtn.disabled = true;

    fetch(optionsUrl(regId), { credentials: 'same-origin' })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        data = payload;
        renderProblems(payload.problems);
        payload.instances.forEach(function (instance) {
          var option = document.createElement('option');
          option.value = instance.id;
          option.textContent = instance.title + ' — ' + instance.start_date
            + (instance.location ? ' — ' + instance.location : '');
          instanceSelect.appendChild(option);
        });
        if (!payload.instances.length && !payload.problems.length) {
          renderProblems(['Немає жодного заходу, придатного для перенесення']);
        }
        renderTariffs();
        renderDifference();
        renderInitiator();
      })
      .catch(function () {
        renderProblems(['Не вдалося завантажити список заходів']);
      });
  });

  instanceSelect.addEventListener('change', function () {
    renderTariffs();
    renderDifference();
  });
  tariffSelect.addEventListener('change', renderDifference);
  initiatorSelect.addEventListener('change', renderInitiator);
})();
