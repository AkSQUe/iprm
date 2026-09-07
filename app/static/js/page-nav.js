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

  // Контракт -- атрибут data-page-nav на контейнері, а не клас посилання:
  // тим самим скриптом користується покажчик секцій в адмінці, де таблетки
  // звуться .admin-pill. Всередині позначеного контейнера будь-яке
  // посилання-якір є пунктом навігації.
  var links = Array.prototype.slice.call(nav.querySelectorAll('a[href^="#"]'));
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

  // На вузькому екрані навігація прокручується горизонтально: активне
  // посилання може опинитися за межами видимої частини стрічки.
  //
  // Рухаємо scrollLeft САМОЇ стрічки, а не scrollIntoView. Той прокручує
  // кожного прокручуваного предка, зокрема документ: на сторінці курсу це
  // непомітно, бо смуга якорів живе в липкій шапці й завжди у кадрі, тож
  // по вертикалі `block: 'nearest'` нічого не робить. Покажчик секцій у
  // налаштуваннях адмінки НЕ липкий -- щойно він іде вгору за край вікна,
  // кожне спрацювання спостерігача повертало сторінку до нього, і
  // прокрутка з'їжджала на початок (плавно, бо html { scroll-behavior:
  // smooth }). Сторінку прокрутити було неможливо.
  function keepInStrip(link) {
    if (nav.scrollWidth <= nav.clientWidth) return;
    var strip = nav.getBoundingClientRect();
    var item = link.getBoundingClientRect();
    if (item.left < strip.left) {
      nav.scrollLeft -= strip.left - item.left;
    } else if (item.right > strip.right) {
      nav.scrollLeft += item.right - strip.right;
    }
  }

  function activate(link) {
    links.forEach(function (l) {
      if (l === link) {
        l.setAttribute('aria-current', 'true');
      } else {
        l.removeAttribute('aria-current');
      }
    });
    keepInStrip(link);
  }

  if (!('IntersectionObserver' in window)) return;

  // Верхня межа -- нижній край липкої смуги: секція вважається активною,
  // коли доходить саме туди, а не до краю вікна.
  //
  // Міряємо шапку, а не саму навігацію: після WS-1 якорі живуть усередині
  // глобальної шапки, і висота рядка посилань (~40px) уже не дорівнює
  // висоті смуги, що перекриває сторінку. Фолбек на nav лишений для
  // вітрини дизайн-системи, де смуга показана окремо.
  var bar = nav.closest('.iprm-header') || nav;
  var offset = bar.getBoundingClientRect().height
    + (parseInt(getComputedStyle(bar).top, 10) || 0);

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
