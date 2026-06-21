import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:5050';
const DIR = 'D:/site-iprm/.preview/shots';
const log = (...a) => console.log(...a);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();

async function shot(name) {
  await page.screenshot({ path: `${DIR}/${name}.png`, fullPage: true });
  log('  shot:', name, '<-', page.url());
}

try {
  // 1) Каталог курсів
  await page.goto(`${BASE}/courses/`, { waitUntil: 'networkidle' });
  await shot('01-catalog');

  // 2) Сторінка курсу
  await page.goto(`${BASE}/courses/plasma-base`, { waitUntil: 'networkidle' });
  await shot('02-course-detail');

  // 3) Клік "Реєстрація" -> редірект на логін (неавторизований)
  await page.goto(`${BASE}/registration/instance/1/register`, { waitUntil: 'networkidle' });
  await shot('03-login-redirect');

  // 4) Логін
  await page.fill('#email', 'demo.participant@example.com');
  await page.fill('#password', 'DemoPass123');
  await Promise.all([
    page.waitForLoadState('networkidle'),
    page.locator('form button[type="submit"], form input[type="submit"]').first().click(),
  ]);

  // 5) Форма реєстрації (НОВИЙ дизайн: без вибору способу оплати)
  if (!page.url().includes('/register')) {
    await page.goto(`${BASE}/registration/instance/1/register`, { waitUntil: 'networkidle' });
  }
  await shot('04-register-form-empty');

  await page.locator('input[name="user_type"]').first().check();
  await page.fill('#last_name', 'Петренко');
  await page.fill('#first_name', 'Іван');
  await page.fill('#middle_name', 'Миколайович');
  await page.fill('#phone', '+380501234567');
  await page.fill('#birth_date', '1985-05-20');
  await page.fill('#education', '2010, НМУ ім. О.О. Богомольця');
  await page.fill('#workplace', 'КНП "Міська лікарня №1"');
  await page.fill('#position', 'лікар-дерматолог');
  await page.locator('input[name="specializations"]').first().check();
  await page.locator('#consent_data').check();
  await shot('05-register-form-filled');

  // 6) Сабміт -> підтвердження (спосіб ще не обрано -> дефолт LiqPay підсвічено)
  await Promise.all([
    page.waitForLoadState('networkidle'),
    page.locator('form[data-validate] button[type="submit"]').click(),
  ]);
  log('  after submit ->', page.url());
  const confUrl = page.url();
  await page.waitForTimeout(700);
  await shot('06-confirmation-default');

  // 7) Дія: завантажити рахунок -> сервер фіксує payment_method=invoice
  const [ download ] = await Promise.all([
    page.waitForEvent('download').catch(() => null),
    page.locator('a[href*="/invoice.pdf"]').first().click(),
  ]);
  if (download) { await download.saveAs(`${DIR}/invoice.pdf`); log('  invoice saved'); }

  // 8) Перезавантажити підтвердження -> тепер підсвічено "Оплата за рахунком"
  await page.goto(confUrl, { waitUntil: 'networkidle' });
  await page.waitForTimeout(300);
  await shot('06b-confirmation-invoice-chosen');

  // 9) Кабінет (після дії -> бейдж "Оплата за рахунком" + кнопка рахунка)
  await page.goto(`${BASE}/auth/account`, { waitUntil: 'networkidle' });
  await shot('07-account');

  // 10) Мобільний вигляд підтвердження
  const mob = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await mob.addCookies(await ctx.cookies());
  const mp = await mob.newPage();
  await mp.goto(confUrl, { waitUntil: 'networkidle' });
  await mp.screenshot({ path: `${DIR}/08-confirmation-mobile.png`, fullPage: true });
  log('  shot: 08-confirmation-mobile');
  await mob.close();

  log('DONE');
} catch (e) {
  log('ERROR:', e.message);
  await shot('zz-error');
} finally {
  await browser.close();
}
