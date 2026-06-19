(function () {
  'use strict';

  var form = document.querySelector('form.admin-form');
  if (!form) return;

  // ---------- error UI ----------
  function group(el) { return el.closest('.form-group') || el.parentNode; }

  function setError(el, msg) {
    el.classList.add('is-invalid');
    var g = group(el);
    var hint = g.querySelector('.form-error--js');
    if (!hint) {
      hint = document.createElement('div');
      hint.className = 'form-error form-error--js';
      g.appendChild(hint);
    }
    hint.textContent = msg;
  }

  function clearError(el) {
    el.classList.remove('is-invalid');
    var hint = group(el).querySelector('.form-error--js');
    if (hint) hint.remove();
  }

  // ---------- normalizers (дзеркало app/utils.py) ----------
  function normalizeName(v) {
    v = (v || '').replace(/\s+/g, ' ').trim();
    if (!v) return '';
    return v.split(' ').map(function (w) {
      return w.split('-').map(function (s) {
        return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : s;
      }).join('-');
    }).join(' ');
  }

  function normalizePhone(v) {
    var d = (v || '').replace(/\D/g, '');
    if (!d) return '';
    if (d.indexOf('380') === 0 && d.length === 12) return '+' + d;
    if (d.charAt(0) === '0' && d.length === 10) return '+38' + d;
    if (d.length === 9) return '+380' + d;
    return '+' + d;
  }

  function lowerTrim(v) { return (v || '').trim().toLowerCase(); }

  // ---------- format checks ----------
  var CYRILLIC = /^[А-ЯЇІЄҐа-яїієґ'’\- ]+$/;
  var UA_PHONE = /^\+380\d{9}$/;
  var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function vName(el, required) {
    var v = el.value.trim();
    if (!v) return required ? 'Обовʼязкове поле.' : '';
    if (!CYRILLIC.test(v)) return 'Лише українські літери (кирилиця). Перевірте розкладку клавіатури.';
    return '';
  }
  function vPhone(el) {
    if (!el.value.trim()) return 'Телефон обовʼязковий.';
    if (!UA_PHONE.test(el.value)) return 'Формат: +380XXXXXXXXX (12 цифр).';
    return '';
  }
  function vEmail(el) {
    var v = el.value.trim();
    if (!v) return '';
    if (!EMAIL.test(v)) return 'Невалідний email. Напр.: name@example.com.';
    return '';
  }

  // ---------- field wiring ----------
  var fields = [
    { id: 'last_name', norm: normalizeName, val: function (e) { return vName(e, true); } },
    { id: 'first_name', norm: normalizeName, val: function (e) { return vName(e, true); } },
    { id: 'middle_name', norm: normalizeName, val: function (e) { return vName(e, false); } },
    { id: 'phone', norm: normalizePhone, val: vPhone },
    { id: 'email', norm: lowerTrim, val: vEmail }
  ];

  fields.forEach(function (f) {
    f.el = document.getElementById(f.id);
    if (!f.el) return;
    f.el.addEventListener('blur', function () {
      if (f.el.value) f.el.value = f.norm(f.el.value);
      var msg = f.val(f.el);
      if (msg) { setError(f.el, msg); } else { clearError(f.el); }
    });
    // М'яко прибираємо помилку, щойно поле стає валідним під час набору.
    f.el.addEventListener('input', function () {
      if (f.el.classList.contains('is-invalid') && !f.val(f.el)) clearError(f.el);
    });
  });

  function validateAll() {
    var first = null;
    fields.forEach(function (f) {
      if (!f.el) return;
      if (f.el.value) f.el.value = f.norm(f.el.value);
      var msg = f.val(f.el);
      if (msg) { setError(f.el, msg); if (!first) first = f.el; }
      else { clearError(f.el); }
    });
    var sel = document.getElementById('instance_id');
    if (sel && sel.tagName === 'SELECT' && !sel.value) {
      setError(sel, 'Оберіть захід.');
      if (!first) first = sel;
    }
    return first;
  }

  form.addEventListener('submit', function (e) {
    var first = validateAll();
    if (first) {
      e.preventDefault();
      first.focus();
      first.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (window.iprmToast) {
        window.iprmToast('Перевірте підсвічені поля та виправте формат.', 'error');
      }
    }
  });

  // ---------- сума оплати за замовчуванням з розкладу ----------
  var sel = document.getElementById('instance_id');
  var amount = document.getElementById('payment_amount');
  if (sel && amount && sel.tagName === 'SELECT') {
    var auto = amount.value.trim() === '';
    amount.addEventListener('input', function () { auto = false; });
    var applyDefault = function () {
      if (!auto) return;
      var opt = sel.options[sel.selectedIndex];
      var price = opt ? (opt.getAttribute('data-price') || '') : '';
      if (price !== '') amount.value = price;
    };
    sel.addEventListener('change', applyDefault);
    applyDefault();
  }
})();
