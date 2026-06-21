import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:5050';
const DIR = 'D:/site-iprm/.preview/shots';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
try {
  // login
  await page.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
  await page.fill('#email', 'demo.participant@example.com');
  await page.fill('#password', 'DemoPass123');
  await Promise.all([page.waitForLoadState('networkidle'),
    page.locator('form button[type="submit"]').first().click()]);
  // confirmation (paid state)
  await page.goto(`${BASE}/registration/1`, { waitUntil: 'networkidle' });
  await page.screenshot({ path: `${DIR}/09-confirmation-paid.png`, fullPage: true });
  console.log('shot 09-confirmation-paid <-', page.url());
  // payment success page
  await page.goto(`${BASE}/payments/success?order_id=REG-1`, { waitUntil: 'networkidle' });
  await page.screenshot({ path: `${DIR}/10-payment-success.png`, fullPage: true });
  console.log('shot 10-payment-success <-', page.url());
  // account (paid)
  await page.goto(`${BASE}/auth/account`, { waitUntil: 'networkidle' });
  await page.screenshot({ path: `${DIR}/11-account-paid.png`, fullPage: true });
  console.log('shot 11-account-paid <-', page.url());
  console.log('DONE');
} catch (e) { console.log('ERR', e.message); }
finally { await browser.close(); }
