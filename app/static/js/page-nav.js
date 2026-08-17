/* page-nav.js -- підсвічування активної секції у навігації сторінкою курсу.
 *
 * Сторінка курсу має близько двадцяти секцій, тож навігація тут -- основний
 * спосіб нею користуватися, а не оздоблення. Скрипт лише позначає поточну
 * секцію: сам перехід робить браузер по якорю, тому без JS навігація
 * повністю робоча (Progressive Enhancement).
 *
 * Активність позначаємо aria-current="true", а не класом: це стан для
 * скрінрідера, і CSS чіпляється до того самого атрибута -- одне джерело
 * правди замість пари "клас + aria".
 */
(function () {
  'use strict';

  var nav = document.querySelector('[data-page-nav]');
  if (!nav) return;

  var links = Array.prototype.slice.call(
    nav.querySelectorAll('.iprm-page-nav__link[href^="#"]')
  );
  if (!links.length) return;

  // Секція -> посилання. Шаблон рендерить лише наявні секції, але сторінку
  // могли зібрати інакше, тож биті якорі просто відкидаємо.
  var map = [];
  links.forEach(function (link) {
    var id = link.getAttribute('href').slice(1);
    if (!id) return;
    var section = document.getElementById(id);
    if (section) map.push({ link: link, section: section });
  });
  if (!map.length) return;

  function activate(link) {
    links.forEach(function (l) {
      if (l === link) {
        l.setAttribute('aria-current', 'true');
      } else {
        l.removeAttribute('aria-current');
      }
    });
    // На вузькому екрані навігація прокручується горизонтально: активне
    // посилання може опинитися за межами видимої частини.
    if (link.scrollIntoView) {
      link.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  }

  if (!('IntersectionObserver' in window)) return;

  // Верхня межа -- нижній край шапки разом із самою навігацією: секція
  // вважається активною, коли доходить саме туди, а не до краю вікна.
  var offset = nav.getBoundingClientRect().height
    + (parseInt(getComputedStyle(nav).top, 10) || 0);

  var visible = [];

  var obs = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      var i = visible.indexOf(entry.target);
      if (entry.isIntersecting) {
        if (i === -1) visible.push(entry.target);
      } else if (i !== -1) {
        visible.splice(i, 1);
      }
    });
    if (!visible.length) return;
    // Кілька секцій у кадрі одночасно -- активною вважаємо найвищу,
    // інакше підсвітка стрибала б уперед на довгих секціях.
    var top = visible.reduce(function (best, el) {
      return el.getBoundingClientRect().top < best.getBoundingClientRect().top ? el : best;
    });
    var pair = map.filter(function (m) { return m.section === top; })[0];
    if (pair) activate(pair.link);
  }, {
    rootMargin: '-' + Math.round(offset) + 'px 0px -55% 0px',
    threshold: 0,
  });

  map.forEach(function (m) { obs.observe(m.section); });
})();
