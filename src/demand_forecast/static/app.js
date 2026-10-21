'use strict';
const KIND='forecast';
const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const pretty=value=>JSON.stringify(value,null,2);
const fmt=(value,d=2)=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d}):'—';
function status(message,error=false){$('status').textContent=message;$('status').classList.toggle('error',error);$('status').setAttribute('role',error?'alert':'status');}
async function request(path,body,timeout=15000){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
  try{const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});
    const json=await response.json();if(!response.ok){const e=new Error(json.error||`HTTP ${response.status}`);e.http=response.status;e.data=json;throw e;}return{data:json,status:response.status};
  }catch(error){if(error.name==='AbortError')throw new Error('Request timed out. The current result was not replaced; retry when the local service is ready.');throw error;}finally{clearTimeout(timer);}
}
async function busy(button,task,message='Calculating…'){
  const label=button.textContent;button.disabled=true;button.textContent='Working…';button.setAttribute('aria-busy','true');status(message);
  try{await task();}catch(error){status(error.message||'The local service is unavailable. Retry the request.',true);}finally{button.disabled=false;button.textContent=label;button.removeAttribute('aria-busy');}
}
function download(name,content,type='application/json'){
  const url=URL.createObjectURL(new Blob([content],{type}));const link=el('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function table(container,headers,rows){
  container.replaceChildren();container.tabIndex=0;const t=el('table');const caption=el('caption',headers.join(' · '));caption.className='small muted';t.append(caption);const head=el('thead'),tr=el('tr');for(const h of headers){const th=el('th',h);th.scope='col';tr.append(th);}head.append(tr);t.append(head);const body=el('tbody');for(const row of rows){const line=el('tr');for(const v of row)line.append(el('td',v==null?'—':String(v)));body.append(line);}t.append(body);container.append(t);
}
function metrics(container,items){container.replaceChildren();const row=el('div',undefined,'metrics');for(const [label,value]of items){const item=el('div',undefined,'metric');item.append(el('strong',value),el('span',label));row.append(item);}container.append(row);}
function routeTab(){let name=location.hash.slice(1)||'workspace';if(!document.querySelector(`[data-panel="${CSS.escape(name)}"]`))name='workspace';for(const p of document.querySelectorAll('[data-panel]'))p.hidden=p.dataset.panel!==name;for(const a of document.querySelectorAll('[data-nav]')){if(a.dataset.nav===name)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}}
addEventListener('hashchange',()=>{routeTab();});routeTab();
let apiSpec,apiEntries=[];
async function setupApi(){
  apiSpec=(await request('/openapi.json')).data;apiEntries=[];
  for(const [path,methods]of Object.entries(apiSpec.paths))for(const [method,definition]of Object.entries(methods))apiEntries.push({path,method:method.toUpperCase(),definition});
  apiEntries.sort((a,b)=>(a.method==='POST'?0:1)-(b.method==='POST'?0:1));$('endpoint').replaceChildren();for(const [i,item]of apiEntries.entries()){const opt=el('option',`${item.method} ${item.path}`);opt.value=i;$('endpoint').append(opt);}
  setApiExample();
}
function setApiExample(){const endpoint=apiEntries[Number($('endpoint').value)];if(!endpoint)return;const post=endpoint.method==='POST';$('api-body').hidden=!post;$('api-get-note').hidden=post;$('api-body').value=pretty(endpoint.definition.requestBody?.content?.['application/json']?.example||{});$('api-help').textContent=endpoint.definition.summary;$('http-status').textContent='Not sent';$('api-response').textContent='Send a request to inspect the response.';}
$('endpoint').addEventListener('change',setApiExample);
$('send-api').addEventListener('click',()=>busy($('send-api'),async()=>{
  const item=apiEntries[Number($('endpoint').value)];let payload;if(item.method==='POST'){try{payload=JSON.parse($('api-body').value);}catch{throw new Error('Request JSON is invalid. Fix it before sending.');}}
  try{const result=await request(item.path,payload);$('http-status').textContent=`HTTP ${result.status}`;$('api-response').textContent=pretty(result.data);status('API response received from the local service.');}
  catch(error){$('http-status').textContent=error.http?`HTTP ${error.http}`:'Request failed';$('api-response').textContent=pretty(error.data||{error:error.message});throw error;}
},'Sending API request…'));
$('copy-curl').addEventListener('click',async()=>{try{const item=apiEntries[Number($('endpoint').value)];const quote=s=>"'"+s.replaceAll("'","'\\''")+"'";let command=`curl ${quote(location.origin+item.path)}`;if(item.method==='POST')command+=` -H 'Content-Type: application/json' --data ${quote($('api-body').value)}`;await navigator.clipboard.writeText(command);status('curl command copied (POSIX shell quoting).');}catch{status('Clipboard is unavailable. The endpoint and JSON body remain visible for copying.',true);}});
async function setupEvidence(meta){$('provenance').textContent=pretty(meta);const response=await request('/api/evidence');$('evidence-files').replaceChildren();for(const file of response.data.files){const li=el('li'),a=el('a',file.name);a.href=file.url;a.download=file.name;li.append(a,el('span',`${fmt(file.bytes/1024,1)} KiB`,'muted mono'));$('evidence-files').append(li);}if(!response.data.files.length)$('evidence-files').append(el('li','No recorded files yet. Run the project CLI first.'));}
async function initialize(){try{$('init-error').hidden=true;await initProject();await setupApi();}catch(error){$('init-error').hidden=false;status(error.message,true);}}
$('retry-init').addEventListener('click',initialize);

let forecastMeta,lastForecast=null,forecastRevision=0;
function invalidateForecast(){forecastRevision++;lastForecast=null;$('download-forecast').disabled=true;$('forecast-kind').textContent='Inputs changed · generate a new forecast';$('forecast-chart').classList.add('busy');status('Inputs changed. The displayed chart is stale; generate a new forecast.');}
for(const id of ['origin','use-history','history-json'])$(id).addEventListener('input',()=>{if(id==='use-history'&&forecastMeta){$('origin').min=$('use-history').checked?'1900-01-01':forecastMeta.origins[0];$('origin').max=$('use-history').checked?'2200-12-31':forecastMeta.origins.at(-1);}invalidateForecast();});
function drawForecast(){if(!lastForecast)return;const container=$('forecast-chart'),width=Math.max(280,container.clientWidth),height=width<600?280:350,pad={l:52,r:18,t:12,b:44},rows=lastForecast.rows,max=Math.max(1,...rows.flatMap(r=>[r.prediction,r.baseline,r.actual||0])),upper=Math.ceil(max/100)*100;const ns='http://www.w3.org/2000/svg';const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('role','img');svg.setAttribute('aria-label',`Hourly rental demand at ${lastForecast.origin}, actual versus model and seasonal baseline. Exact values are in the hourly data table.`);const draw=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;svg.append(n);return n;};const x=i=>pad.l+i*(width-pad.l-pad.r)/23,y=v=>height-pad.b-v*(height-pad.t-pad.b)/upper;
  for(let i=0;i<=5;i++){const value=upper*i/5;draw('line',{x1:pad.l,y1:y(value),x2:width-pad.r,y2:y(value),stroke:'#303030','stroke-dasharray':'2 3'});draw('text',{x:pad.l-10,y:y(value)+4,fill:'#b8bec8','font-size':12,'text-anchor':'end'},Math.round(value));}
  const ticks=width<600?[0,6,12,18,23]:Array.from({length:24},(_,i)=>i);for(const i of ticks)draw('text',{x:x(i),y:height-pad.b+23,fill:'#b8bec8','font-size':12,'text-anchor':'middle'},i);draw('text',{x:width/2,y:height-3,fill:'#b8bec8','font-size':12,'text-anchor':'middle'},'Hour of day · rentals per hour');
  for(const[field,color,dash]of [['baseline','#92979e','6 5'],['actual','#f3f3f5',''],['prediction','#258dff','']]){let segment=[];const flush=()=>{if(segment.length){draw('polyline',{points:segment.join(' '),fill:'none',stroke:color,'stroke-width':2,'stroke-dasharray':dash});segment=[];}};for(const[r,i]of rows.map((r,i)=>[r,i])){if(r[field]==null){flush();continue;}segment.push(`${x(i)},${y(r[field])}`);draw('circle',{cx:x(i),cy:y(r[field]),r:width<500?2:3,fill:color});}flush();}
  container.replaceChildren(svg);
}
async function generateForecast(){const revision=forecastRevision;let history;if($('use-history').checked){try{history=JSON.parse($('history-json').value);}catch{throw new Error('History JSON is invalid.');}if(!Array.isArray(history))throw new Error('Custom history must be a JSON array.');}const response=await request('/api/forecast',{origin:$('origin').value,...(history!==undefined?{history}:{})});if(revision!==forecastRevision){status('Inputs changed during the request. Generate again to see the current forecast.');return;}lastForecast=response.data;$('forecast-chart').classList.remove('busy');drawForecast();$('forecast-kind').textContent=lastForecast.kind==='historical_replay'?'Historical replay · measured data':'Custom history · outside recorded benchmark';const observed=lastForecast.rows.filter(r=>r.actual!==null),mae=observed.length?observed.reduce((sum,r)=>sum+Math.abs(r.prediction-r.actual),0)/observed.length:null;$('forecast-caption').textContent=`${lastForecast.selected_model} · origin ${lastForecast.origin.slice(0,10)} · ${observed.length}/24 observed target hours${mae!==null?` · this day MAE ${fmt(mae)} rentals`:''}. ${lastForecast.warnings.join(' ')}`;table($('forecast-table'),['Timestamp','Model','Baseline','Actual','Lag 24h','Lag 168h'],lastForecast.rows.map(r=>[r.timestamp,fmt(r.prediction),fmt(r.baseline),r.actual===null?'Unknown':fmt(r.actual,0),r.lag24_observed?'Observed':'Missing',r.lag168_observed?'Observed':'Missing']));$('download-forecast').disabled=false;status('24 hourly predictions calculated using information available before the origin.');}
$('forecast-form').addEventListener('submit',e=>{e.preventDefault();busy($('generate'),generateForecast);});
$('download-forecast').addEventListener('click',()=>{if(!lastForecast)return;const fields=['timestamp','horizon','prediction','baseline','actual','lag24_observed','lag168_observed'];download('forecast.csv',[fields.join(','),...lastForecast.rows.map(row=>fields.map(k=>row[k]??'').join(','))].join('\n'),'text/csv');});
new ResizeObserver(drawForecast).observe($('forecast-chart'));
const evaluationUI=ForecastEvaluation.create({request,$,table,fmt});
$('diagnostics-retry').addEventListener('click',evaluationUI.load);
async function initProject(){forecastMeta=(await request('/api/meta')).data;const origins=forecastMeta.origins||forecastMeta.available_origins;$('origin').min=origins[0];$('origin').max=origins.at(-1);$('origin').value=origins.includes('2012-11-01')?'2012-11-01':origins[0];const m=forecastMeta.metrics,test=m.test;$('forecast-summary').textContent=`${forecastMeta.selected_model} · final holdout MAE ${fmt(test.selected.mae)} rentals/h. Baseline ${fmt(test.baseline.mae)}.`;metrics($('forecast-metrics'),[['Model MAE',fmt(test.selected.mae)],['Baseline MAE',fmt(test.baseline.mae)],['Model RMSE',fmt(test.selected.rmse)],['Observed test hours',fmt(test.selected.n,0)]]);$('evaluation-json').textContent=pretty(m);void evaluationUI.load();await setupEvidence({source:forecastMeta.source,splits:forecastMeta.splits,artifact:forecastMeta.provenance,limitations:forecastMeta.limitations});await generateForecast();}
initialize();
