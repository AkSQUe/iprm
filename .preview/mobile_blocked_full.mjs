import { chromium, devices } from 'playwright';
const BASE='http://127.0.0.1:5050', DIR='D:/site-iprm/.preview/shots';
const b=await chromium.launch();
const ctx=await b.newContext({...devices['iPhone 13']});
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r=>r.abort());
const p=await ctx.newPage();
try{
  await p.goto(`${BASE}/auth/login`,{waitUntil:'networkidle'});
  await p.fill('#email','demo.participant@example.com'); await p.fill('#password','DemoPass123');
  await Promise.all([p.waitForLoadState('networkidle'),p.locator('form button[type="submit"]').first().click()]);
  await p.goto(`${BASE}/admin/courses`,{waitUntil:'networkidle'}); await p.waitForTimeout(900);
  await p.screenshot({path:`${DIR}/mobile-blocked-full.png`,fullPage:true});
  console.log('shot done');
}catch(e){console.log('ERR',e.message)} finally{await b.close();}
