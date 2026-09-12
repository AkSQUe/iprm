import { chromium, devices } from 'playwright';
const BASE='http://127.0.0.1:5050', DIR='D:/site-iprm/.preview/shots';
const b=await chromium.launch();
async function login(ctx){const p=await ctx.newPage();await p.goto(`${BASE}/auth/login`,{waitUntil:'networkidle'});await p.fill('#email','demo.participant@example.com');await p.fill('#password','DemoPass123');await Promise.all([p.waitForLoadState('networkidle'),p.locator('form button[type="submit"]').first().click()]);return p;}
// 1) Desktop instances (має pills із динамічними іконками + дії)
let ctx=await b.newContext({viewport:{width:1440,height:1000}});
let p=await login(ctx);
await p.goto(`${BASE}/admin/instances`,{waitUntil:'networkidle'});await p.waitForTimeout(400);
await p.screenshot({path:`${DIR}/icons-desktop-instances.png`,fullPage:true});
console.log('desktop instances shot');
await ctx.close();
// 2) Mobile iPhone з ЗАБЛОКОВАНИМ Google -- вихідний баг-сценарій
ctx=await b.newContext({...devices['iPhone 13']});
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r=>r.abort());
p=await login(ctx);
await p.goto(`${BASE}/admin/instances`,{waitUntil:'networkidle'});await p.waitForTimeout(800);
const nav=await p.$('.admin-sidebar'); if(nav) await nav.screenshot({path:`${DIR}/icons-mobile-blocked-sidebar.png`});
const pills=await p.$('.admin-filter-pills'); if(pills) await pills.screenshot({path:`${DIR}/icons-mobile-blocked-pills.png`});
console.log('mobile-blocked shots');
await b.close();
