import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:5050';
const DIR = 'D:/site-iprm/.preview/shots';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const p = await ctx.newPage();

// Вимірює margin-top між послідовними .form-section у межах кожного контейнера.
async function measure(label) {
  const data = await p.evaluate(() => {
    const out = [];
    document.querySelectorAll('.form-section').forEach(el => {
      const prev = el.previousElementSibling;
      if (prev && prev.classList.contains('form-section')) {
        const cs = getComputedStyle(el);
        const parent = el.parentElement;
        const pcs = getComputedStyle(parent);
        out.push({
          parent: parent.className.trim(),
          display: pcs.display,
          gap: pcs.rowGap,
          marginTop: cs.marginTop,
        });
      }
    });
    return out;
  });
  console.log(`\n[${label}] consecutive .form-section pairs:`);
  data.forEach(d => console.log(`  parent="${d.parent}" display=${d.display} gap=${d.gap} margin-top=${d.marginTop}`));
}

try {
  await p.goto(`${BASE}/auth/login`, { waitUntil: 'networkidle' });
  await p.fill('#email', 'demo.participant@example.com');
  await p.fill('#password', 'DemoPass123');
  await Promise.all([p.waitForLoadState('networkidle'),
    p.locator('form button[type="submit"], form input[type="submit"]').first().click()]);

  const pages = [
    ['integration-ga', '/admin/google-analytics'],   // plain .admin-layout -> expect margin 24
    ['marketing', '/admin/marketing'],               // .admin-layout--stack -> expect margin 0
    ['notifications', '/admin/notifications'],        // .admin-layout--stack -> expect margin 0
    ['course-edit', '/admin/courses/1/edit'],         // .admin-form -> expect margin 0
  ];
  for (const [name, url] of pages) {
    await p.goto(`${BASE}${url}`, { waitUntil: 'networkidle' });
    await p.waitForTimeout(200);
    await measure(name);
    await p.screenshot({ path: `${DIR}/gap-${name}.png`, fullPage: true });
  }
  console.log('\nDONE');
} catch (e) { console.log('ERR', e.message); }
finally { await browser.close(); }
