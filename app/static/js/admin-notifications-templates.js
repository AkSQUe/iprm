(function() {
  // Blob URL замість srcdoc -- уникає sandbox обмежень браузера
  document.querySelectorAll('iframe[data-html]').forEach(function(frame) {
    var html = frame.getAttribute('data-html');
    if (!html) return;
    var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    frame.src = URL.createObjectURL(blob);
    frame.removeAttribute('data-html');
  });

  var tabs = document.querySelectorAll('.template-tab');
  var panels = document.querySelectorAll('.template-preview');
  tabs.forEach(function(tab) {
    tab.addEventListener('click', function() {
      tabs.forEach(function(t) {
        t.classList.remove('template-tab--active');
        t.setAttribute('aria-selected', 'false');
      });
      panels.forEach(function(p) { p.classList.remove('template-preview--active'); });
      tab.classList.add('template-tab--active');
      tab.setAttribute('aria-selected', 'true');
      var panel = document.getElementById(tab.getAttribute('data-target'));
      if (panel) panel.classList.add('template-preview--active');
    });
  });
})();
