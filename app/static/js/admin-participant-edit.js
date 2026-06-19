(function () {
  // Сторінка "Новий учасник" (з вибором заходу): сума оплати за замовчуванням
  // береться з налаштувань розкладу обраного заходу (data-price на <option>).
  // Якщо адмін вручну змінив суму -- більше не перезаписуємо.
  var sel = document.getElementById('instance_id');
  var amount = document.getElementById('payment_amount');
  if (!sel || !amount || sel.tagName !== 'SELECT') return;

  // Авто-режим активний, поки поле порожнє (свіжа форма). Ручне введення
  // вимикає авто-підстановку, щоб не затерти введене значення.
  var auto = amount.value.trim() === '';
  amount.addEventListener('input', function () { auto = false; });

  function applyDefault() {
    if (!auto) return;
    var opt = sel.options[sel.selectedIndex];
    var price = opt ? (opt.getAttribute('data-price') || '') : '';
    if (price !== '') amount.value = price;
  }

  sel.addEventListener('change', applyDefault);
  applyDefault(); // початкове заповнення для попередньо обраного заходу
})();
