/* reg-tariffs.js -- живе оновлення суми при виборі тарифу на формі
 * реєстрації. Радіо тарифу несе data-price; усі [data-tariff-price]
 * (шапка "Вартість" і кнопка submit) отримують обрану ціну.
 * Без JS показується "від N грн" -- сервер все одно рахує суму сам. */
(function () {
  'use strict';

  var radios = document.querySelectorAll('[data-tariff-radio]');
  var targets = document.querySelectorAll('[data-tariff-price]');
  if (!radios.length || !targets.length) return;

  function update(price) {
    targets.forEach(function (el) {
      el.textContent = price + ' ₴';
    });
  }

  radios.forEach(function (radio) {
    radio.addEventListener('change', function () {
      if (radio.checked) update(radio.getAttribute('data-price'));
    });
    if (radio.checked) update(radio.getAttribute('data-price'));
  });
})();
