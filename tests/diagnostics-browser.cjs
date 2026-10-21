module.exports=async function(page,{base='http://127.0.0.1:8766'}={}) {
  const cases=[],errors=[];const check=(ok,label)=>{if(!ok)throw new Error(label);cases.push(label);};page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/?test=paired-'+Date.now()+'#evaluation');await page.locator('#diagnostics-content').waitFor();
  const response=await page.request.get(base+'/api/diagnostics'),data=await response.json();
  check(response.status()===200&&data.overall.n===3488,'live diagnostic contains 3488 paired targets');
  const summary=await page.locator('#diagnostics-summary').textContent();
  check(['2/5 months','8/24 target hours','65/147 test days'].every(s=>summary.includes(s)),'visible loss counts match the saved predictions');
  check(await page.locator('#month-comparison tbody tr').count()===5,'all five monthly slices shown');
  check(await page.locator('#hour-comparison tbody tr').count()===24,'all 24 target hours shown');
  check(await page.locator('#day-comparison tbody tr').count()===147,'all 147 daily slices remain inspectable');
  check((await page.locator('#hour-comparison tbody tr').filter({hasText:'08:00'}).textContent()).includes('+20.797 (worse)'),'08:00 loss has the correct sign and magnitude');
  check((await page.locator('#month-comparison tbody tr').filter({hasText:'2012-08'}).textContent()).includes('+5.104 (worse)'),'August model loss is visible');
  check((await page.locator('#overall-comparison').textContent()).includes('-4.536 (better)'),'overall gain is distinct from slice failures');
  check((await page.locator('#candidate-comparison').textContent()).includes('Selected on validation'),'model selection remains tied to validation');
  for(const id of ['diagnostics-json','evaluation-json'])check(await page.locator('#'+id).evaluate(n=>n.closest('details')?.open===false),id+' is collapsed by default');
  const geometry=[];
  for(const width of [304,375,768,1280]){await page.setViewportSize({width,height:900});let actual=await page.evaluate(()=>innerWidth);if(Math.abs(actual-width)>1){await page.setViewportSize({width:Math.round(width*width/actual),height:900});actual=await page.evaluate(()=>innerWidth);}geometry.push({requested:width,actual});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'no document overflow at CSS width '+width);}
  await page.setViewportSize({width:304,height:900});
  check(await page.locator('#month-comparison tbody tr').first().locator('td').nth(1).evaluate(n=>n.getBoundingClientRect().right<=innerWidth+1),'signed monthly delta is visible without horizontal scrolling at 304 px');
  await page.route('**/api/diagnostics',r=>r.fulfill({status:503,json:{error:'QA unavailable'}}));await page.goto(base+'/?test=paired-fail-'+Date.now()+'#evaluation');await page.locator('#diagnostics-message').filter({hasText:'Comparison unavailable'}).waitFor();
  check(await page.locator('#diagnostics-content').isHidden()&&await page.locator('#diagnostics-retry').isEnabled(),'diagnostic failure hides stale results and permits retry');
  await page.locator('[data-nav=workspace]').click();await page.locator('#generate').click();await page.locator('#status').filter({hasText:'24 hourly predictions calculated'}).waitFor();
  check(await page.locator('#download-forecast').isEnabled(),'diagnostic failure does not break forecasting');
  await page.locator('[data-nav=evaluation]').click();await page.unroute('**/api/diagnostics');
  await page.route('**/api/diagnostics',r=>r.fulfill({json:{schema_version:1,overall:{n:0},by_month:[],by_hour:[],by_day:[],validation_candidates:[]}}));
  await page.locator('#diagnostics-retry').click();await page.locator('#diagnostics-message').filter({hasText:'No paired diagnostic targets'}).waitFor();check(await page.locator('#diagnostics-content').isHidden(),'empty data is not rendered as zero model error');
  await page.unroute('**/api/diagnostics');await page.locator('#diagnostics-retry').click();await page.locator('#diagnostics-content').waitFor();
  check(await page.locator('#month-comparison tbody tr').count()===5,'diagnostics recover after service and empty-data failures');
  let releaseDiagnostic;const heldDiagnostic=new Promise(resolve=>releaseDiagnostic=resolve);
  const hold=async route=>{await heldDiagnostic;await route.continue();};
  await page.route('**/api/diagnostics',hold);
  try {
    await page.goto(base+'/?test=paired-pending-'+Date.now()+'#workspace');
    await page.waitForFunction(()=>!document.querySelector('#download-forecast').disabled);
    check(await page.locator('#endpoint option').count()>0,'API setup completes while optional diagnostic is pending');
    check(await page.locator('#diagnostics-region').getAttribute('aria-busy')==='true','forecast is available before optional diagnostic resolves');
  } finally {
    const diagnosticResponse=page.waitForResponse(response=>response.url().endsWith('/api/diagnostics'));
    releaseDiagnostic();await diagnosticResponse;
  }
  await page.unroute('**/api/diagnostics',hold);
  check(errors.length===0,'no uncaught page errors');return {checks:cases.length,cases,geometry};
};
