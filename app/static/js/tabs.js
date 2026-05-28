/* tabs.js — табовий перемикач панелей.

   Розмітка:
     <div data-iprm-tabs>
       <div class="iprm-tabs__list" role="tablist" aria-label="...">
         <button data-tab-trigger="key1" data-tab-default>...</button>
         <button data-tab-trigger="key2">...</button>
       </div>
       <div data-tab-panel="key1">...</div>
       <div data-tab-panel="key2">...</div>
     </div>

   Активним стартує тригер з data-tab-default, інакше перший.
   ARIA: role=tab / aria-selected / aria-controls; role=tabpanel / aria-labelledby.
   Клавіатура: Left/Right циклічно по тригерах, Home/End — крайні.
   Vanilla JS. Single Responsibility: лише перемикання. */
(function () {
  'use strict';

  var groupSeq = 0;

  function initGroup(group) {
    if (group.__iprmTabsBound) return;
    group.__iprmTabsBound = true;
    groupSeq += 1;

    var triggers = Array.prototype.slice.call(
      group.querySelectorAll('[data-tab-trigger]')
    );
    var panels = Array.prototype.slice.call(
      group.querySelectorAll('[data-tab-panel]')
    );
    if (!triggers.length || !panels.length) return;

    function panelFor(key) {
      for (var i = 0; i < panels.length; i++) {
        if (panels[i].getAttribute('data-tab-panel') === key) return panels[i];
      }
      return null;
    }

    triggers.forEach(function (trig, i) {
      var key = trig.getAttribute('data-tab-trigger');
      var panel = panelFor(key);
      if (!panel) return;
      var trigId = 'iprm-tab-t-' + groupSeq + '-' + i;
      var panelId = 'iprm-tab-p-' + groupSeq + '-' + i;
      trig.id = trig.id || trigId;
      panel.id = panel.id || panelId;
      trig.setAttribute('role', 'tab');
      trig.setAttribute('aria-controls', panel.id);
      trig.setAttribute('aria-selected', 'false');
      trig.setAttribute('tabindex', '-1');
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', trig.id);
      panel.setAttribute('tabindex', '0');
    });

    function activate(key, focus) {
      triggers.forEach(function (trig) {
        var isActive = trig.getAttribute('data-tab-trigger') === key;
        trig.setAttribute('aria-selected', isActive ? 'true' : 'false');
        trig.setAttribute('tabindex', isActive ? '0' : '-1');
        var panel = panelFor(trig.getAttribute('data-tab-trigger'));
        if (panel) panel.classList.toggle('is-active', isActive);
        if (isActive && focus) trig.focus();
      });
    }

    triggers.forEach(function (trig, i) {
      trig.addEventListener('click', function (e) {
        e.preventDefault();
        activate(trig.getAttribute('data-tab-trigger'), false);
      });
      trig.addEventListener('keydown', function (e) {
        var k = e.key;
        if (k !== 'ArrowLeft' && k !== 'ArrowRight'
            && k !== 'Home' && k !== 'End') return;
        e.preventDefault();
        var next = i;
        if (k === 'ArrowLeft') next = (i - 1 + triggers.length) % triggers.length;
        else if (k === 'ArrowRight') next = (i + 1) % triggers.length;
        else if (k === 'Home') next = 0;
        else if (k === 'End') next = triggers.length - 1;
        activate(triggers[next].getAttribute('data-tab-trigger'), true);
      });
    });

    // Початково активний — той що з data-tab-default, інакше перший
    var initial = null;
    for (var i = 0; i < triggers.length; i++) {
      if (triggers[i].hasAttribute('data-tab-default')) {
        initial = triggers[i].getAttribute('data-tab-trigger');
        break;
      }
    }
    if (!initial) initial = triggers[0].getAttribute('data-tab-trigger');
    activate(initial, false);
  }

  function init() {
    document.querySelectorAll('[data-iprm-tabs]').forEach(initGroup);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
