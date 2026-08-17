/* meta-pixel-test.js -- надсилання тестової події з адмінки.

   Ініціалізацію Pixel робить meta-pixel.js: сторінка перевірки -- єдиний
   ендпоінт адмінки, де services/meta_pixel.py дозволяє його вставити. Тут
   лише кнопка, що шле подію і показує результат.

   Подія нестандартна -- trackCustom('IPRMTestEvent'): якби ми слали
   стандартний Lead чи Purchase, кожна перевірка засмічувала б звіти
   конверсій вигаданими заявками й покупками.

   Успіх тут означає "браузер прийняв виклик і скрипт долетів", а не
   "Meta зарахувала подію" -- останнє видно лише в Events Manager, тож
   посилання туди дає сам шаблон. */
(function () {
  'use strict';

  var btn = document.getElementById('pixel-test-send');
  var out = document.getElementById('pixel-test-result');
  if (!btn || !out) return;

  btn.addEventListener('click', function () {
    if (typeof window.fbq !== 'function') {
      // Найчастіша причина -- блокувальник реклами у браузері адміністратора.
      out.textContent = 'fbq недоступний: скрипт Pixel не завантажився. '
        + 'Найімовірніше його заблокував блокувальник реклами – перевірте '
        + 'у вікні без розширень.';
      out.hidden = false;
      return;
    }
    try {
      window.fbq('trackCustom', 'IPRMTestEvent', {
        source: 'admin',
        sent_at: new Date().toISOString()
      });
      out.textContent = 'Подію IPRMTestEvent надіслано. Перевірте її в '
        + 'Events Manager -> Test Events (з\'являється протягом хвилини).';
    } catch (e) {
      out.textContent = 'Помилка надсилання: ' + (e && e.message ? e.message : e);
    }
    out.hidden = false;
  });
})();
