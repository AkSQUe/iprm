/* progress-fill.js -- заповнення смужки прогресу з data-атрибута.
 *
 * Ширина -- це ДАНІ (скільки місць зайнято), а не оформлення, тому в
 * шаблоні вона жити не може: інлайн-стилі в проєкті заборонені. Шаблон
 * віддає число у [data-progress], скрипт кладе його в CSS-змінну
 * --iprm-progress, а всю візуалізацію робить CSS.
 *
 * Смужку рендеримо з [hidden]: без JS порожній індикатор читався б як
 * "зайнято 0%", тобто брехав. Текстова інформація поруч лишається завжди,
 * тож нічого не втрачається (Progressive Enhancement).
 */
(function () {
  'use strict';

  var fills = document.querySelectorAll('[data-progress]');
  if (!fills.length) return;

  Array.prototype.forEach.call(fills, function (el) {
    var value = parseFloat(el.getAttribute('data-progress'));
    if (isNaN(value)) return;
    // Значення приходить із розрахунку "зайнято/усього" -- підстраховуємось
    // від від'ємних і >100 (скасування реєстрацій, ручні правки місткості).
    value = Math.max(0, Math.min(100, value));
    el.style.setProperty('--iprm-progress', value + '%');

    var track = el.closest('.iprm-progress');
    if (track) track.hidden = false;
  });
})();
