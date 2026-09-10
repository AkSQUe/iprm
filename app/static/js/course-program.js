/* course-program.js — програма курсу: акордеон на мобільному, дві колонки
   на десктопі.

   Працює з розміткою partials/_course_program.html:
     <div class="iprm-program" data-program-accordion>
       <h3 class="iprm-program__head">
         <button class="iprm-program__trigger" aria-controls="ID" aria-expanded>
       <div class="iprm-program__panel" id="ID">
       ... (пари йдуть підряд)

   Дві речі, і обидві навмисно тут, а не в CSS:

   1. Розкриття. Відкрита рівно одна панель; висота анімується, як у
      faq-accordion.js. Окремий файл, а не спільний модуль із FAQ: там
      <details>/<summary> і власна семантика, спільні в них лише кадри
      анімації.
   2. Колонки. На десктопі заголовки переїжджають у .iprm-program__nav,
      панелі -- у .iprm-program__stage. Сіткою це не робиться: панель,
      розтягнута на всі рядки (grid-row: 1 / -1), роздає свою висоту
      рядкам лівої колонки, і перелік блоків розповзається.

   Без скрипта DOM лишається плоским акордеоном з відкритими панелями --
   сторінка читається, тільки довша (Progressive Enhancement). */
(function () {
  'use strict';

  var DURATION = 280;
  var DESKTOP = '(min-width: 769px)';

  function panelOf(trigger) {
    return document.getElementById(trigger.getAttribute('aria-controls'));
  }

  function close(trigger, panel, animate) {
    trigger.setAttribute('aria-expanded', 'false');
    if (!animate) {
      panel.hidden = true;
      return;
    }
    panel.style.height = panel.offsetHeight + 'px';
    panel.style.overflow = 'hidden';
    requestAnimationFrame(function () {
      panel.style.transition = 'height ' + DURATION + 'ms ease';
      panel.style.height = '0px';
    });
    window.setTimeout(function () {
      panel.hidden = true;
      panel.style.transition = '';
      panel.style.height = '';
      panel.style.overflow = '';
    }, DURATION);
  }

  function open(trigger, panel, animate) {
    trigger.setAttribute('aria-expanded', 'true');
    panel.hidden = false;
    if (!animate) return;
    var target = panel.scrollHeight;
    panel.style.overflow = 'hidden';
    panel.style.height = '0px';
    requestAnimationFrame(function () {
      panel.style.transition = 'height ' + DURATION + 'ms ease';
      panel.style.height = target + 'px';
    });
    window.setTimeout(function () {
      panel.style.transition = '';
      panel.style.height = '';
      panel.style.overflow = '';
    }, DURATION);
  }

  /* Дві колонки збираються переносом вузлів, а не порядком у сітці.
     Обгортки створюються один раз і далі просто наповнюються: у режимі
     акордеона вони віддають вміст назад у контейнер, зберігаючи пари
     "заголовок -> панель" підряд. */
  function layout(program, pairs, desktop) {
    var nav = program.querySelector('.iprm-program__nav');
    var stage = program.querySelector('.iprm-program__stage');
    if (desktop) {
      if (!nav) {
        nav = document.createElement('div');
        nav.className = 'iprm-program__nav';
        stage = document.createElement('div');
        stage.className = 'iprm-program__stage';
        program.appendChild(nav);
        program.appendChild(stage);
      }
      pairs.forEach(function (pair) {
        nav.appendChild(pair.head);
        stage.appendChild(pair.panel);
      });
    } else if (nav) {
      pairs.forEach(function (pair) {
        program.appendChild(pair.head);
        program.appendChild(pair.panel);
      });
      nav.remove();
      stage.remove();
    }
    program.classList.toggle('iprm-program--columns', desktop);
  }

  function init(program) {
    var triggers = program.querySelectorAll('.iprm-program__trigger');
    var pairs = [];

    triggers.forEach(function (trigger) {
      var panel = panelOf(trigger);
      if (!panel) return;
      pairs.push({ head: trigger.parentNode, panel: panel, trigger: trigger });
      // Стартовий стан із сервера: відкритий перший блок.
      if (trigger.getAttribute('aria-expanded') !== 'true') {
        close(trigger, panel, false);
      }
      trigger.addEventListener('click', function () {
        if (trigger.getAttribute('aria-expanded') === 'true') {
          // На десктопі права колонка не має лишатись порожньою, тож
          // повторний клік по відкритому блоку там нічого не робить.
          if (program.classList.contains('iprm-program--columns')) return;
          close(trigger, panel, true);
          return;
        }
        pairs.forEach(function (other) {
          if (other.trigger !== trigger &&
              other.trigger.getAttribute('aria-expanded') === 'true') {
            close(other.trigger, other.panel, true);
          }
        });
        open(trigger, panel, true);
      });
    });

    if (!pairs.length) return;

    var query = window.matchMedia(DESKTOP);
    var apply = function () { layout(program, pairs, query.matches); };
    apply();
    // addListener -- запасний шлях для Safari до 14.
    if (query.addEventListener) {
      query.addEventListener('change', apply);
    } else if (query.addListener) {
      query.addListener(apply);
    }
  }

  function boot() {
    document.querySelectorAll('[data-program-accordion]').forEach(init);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
