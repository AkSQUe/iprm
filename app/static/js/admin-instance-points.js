(function () {
  // Формат заходу вирішує, яке з двох полів балів має сенс. Приховане поле
  // лишається в DOM і далі сабмітить своє значення: перемикання формату не
  // повинно мовчки стирати бали, бо захід нерідко стає гібридним пізніше.
  var select = document.getElementById('event_format');
  var groups = document.querySelectorAll('[data-cpd-format]');
  if (!select || !groups.length) return;

  function sync() {
    var format = select.value;
    for (var i = 0; i < groups.length; i++) {
      var wanted = groups[i].getAttribute('data-cpd-format');
      groups[i].hidden = !(format === 'hybrid' || format === wanted);
    }
  }

  select.addEventListener('change', sync);
  sync();
})();
