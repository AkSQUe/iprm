import { chromium, devices } from 'playwright';
const BASE = 'http://127.0.0.1:5050';
const DIR = 'D:/site-iprm/.preview/shots';
const browser = await chromium.launch();
const ctx = await browser.newContext({ ...devices['iPhone 13'] });
const p = await ctx.newPage();
try {
  // login
  await p.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
  await p.fill('#email', 'demo.participant@example.com');
  await p.fill('#password', 'DemoPass123');
  await Promise.all([p.waitForLoadState('networkidle'),
    p.locator('form button[type="submit"], form input[type="submit"]').first().click()]);

  await p.goto(`${BASE}/admin/courses`, { waitUntil: 'networkidle' });
  await p.waitForTimeout(1200);

  const info = await p.evaluate(async () => {
    await (document.fonts ? document.fonts.ready : Promise.resolve());
    const fontLoaded = document.fonts ? document.fonts.check('24px "Material Symbols Rounded"') : 'no-api';
    const els = [...document.querySelectorAll('.material-symbols-rounded')].slice(0, 6);
    const sample = els.map(el => {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return {
        text: el.textContent.trim(),
        fontFamily: cs.fontFamily,
        fontSize: cs.fontSize,
        width: cs.width, height: cs.height, overflow: cs.overflow,
        boxW: Math.round(r.width), boxH: Math.round(r.height),
      };
    });
    return { fontLoaded, count: document.querySelectorAll('.material-symbols-rounded').length, sample };
  });
  console.log('font 24px Material Symbols Rounded loaded:', info.fontLoaded);
  console.log('icon count:', info.count);
  info.sample.forEach((s, i) => console.log(`  [${i}] "${s.text}" family=${s.fontFamily} size=${s.fontSize} w/h=${s.width}/${s.height} overflow=${s.overflow} box=${s.boxW}x${s.boxH}`));

  await p.screenshot({ path: `${DIR}/mobile-admin-courses.png`, fullPage: true });
  // crop sidebar nav (icons area) for a close look
  const nav = await p.$('.admin-sidebar');
  if (nav) await nav.screenshot({ path: `${DIR}/mobile-admin-sidebar.png` });
  console.log('DONE');
} catch (e) { console.log('ERR', e.message); }
finally { await browser.close(); }
