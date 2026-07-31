/* reg-tariffs.js -- реакція форми реєстрації на вибір тарифу.
 *
 * 1) Сума. Радіо тарифу несе data-price; усі [data-tariff-price] (шапка
 *    "Вартість" і кнопка submit) отримують обрану ціну. Без JS показується
 *    "від N грн" -- сервер усе одно рахує суму сам.
 *
 * 2) Підтвердження очної участі на ГІБРИДНОМУ заході. Там частина тарифів
 *    онлайнові, частина очні, тож блок [data-presence-confirm] має сенс лише
 *    для других: інакше людина, яка купує онлайн-доступ, підтверджує приїзд
 *    до іншого міста. Радіо несе data-presence="1|0".
 *
 *    Видимість і required перемикаються РАЗОМ: прихована, але обов'язкова
 *    галочка не дає відправити форму, а браузер каже лише "not focusable".
 *    Блоків два: банер міста вгорі сторінки й галочки підтвердження перед
 *    згодами. Для суто офлайн-заходів у них немає data-presence-confirm --
 *    вони видимі й обов'язкові завжди, як і раніше.
 */
(function () {
  'use strict';

  var radios = document.querySelectorAll('[data-tariff-radio]');
  if (!radios.length) return;

  var priceTargets = document.querySelectorAll('[data-tariff-price]');
  // Блоків кілька: банер міста вгорі й галочки підтвердження нижче.
  var presenceBlocks = document.querySelectorAll('[data-presence-confirm]');

  function updatePrice(price) {
    priceTargets.forEach(function (el) {
      el.textContent = price + ' ₴';
    });
  }

  function updatePresence(radio) {
    if (!presenceBlocks.length) return;
    // Немає атрибута -> вважаємо очною участю: пропущене попередження про
    // поїздку дорожче за зайве.
    var needed = radio.getAttribute('data-presence') !== '0';
    presenceBlocks.forEach(function (block) {
      block.hidden = !needed;
      block.querySelectorAll('input[type="checkbox"]').forEach(function (input) {
        if (needed) {
          input.setAttribute('required', 'required');
        } else {
          input.removeAttribute('required');
          input.checked = false;
        }
      });
    });
  }

  function apply(radio) {
    updatePrice(radio.getAttribute('data-price'));
    updatePresence(radio);
  }

  radios.forEach(function (radio) {
    radio.addEventListener('change', function () {
      if (radio.checked) apply(radio);
    });
    if (radio.checked) apply(radio);
  });
})();
