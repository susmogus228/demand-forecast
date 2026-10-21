'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');

test('pending optional diagnostics do not delay forecast, evidence or API startup',async()=>{
  const nodes=new Map(),calls=[];
  function node(){return {children:[],value:'0',checked:false,hidden:false,disabled:false,clientWidth:320,
    classList:{toggle(){},add(){},remove(){}},addEventListener(){},setAttribute(){},removeAttribute(){},
    replaceChildren(...values){this.children=values;},append(...values){this.children.push(...values);}};}
  const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  const metrics={test:{selected:{mae:4,rmse:5,n:24},baseline:{mae:6}}};
  const rows=Array.from({length:24},(_,hour)=>({timestamp:`2012-11-01T${String(hour).padStart(2,'0')}:00:00`,horizon:hour,prediction:4,baseline:6,actual:3,lag24_observed:true,lag168_observed:true}));
  let completeDiagnostic;
  const diagnostic=new Promise(resolve=>{completeDiagnostic=resolve;});
  const responses={
    '/api/meta':{origins:['2012-11-01'],selected_model:'ridge',metrics},
    '/api/evidence':{files:[]},
    '/api/forecast':{rows,selected_model:'ridge',kind:'historical_replay',origin:'2012-11-01T00:00:00',warnings:[]},
    '/openapi.json':{paths:{'/api/health':{get:{summary:'Local service'}}}},
  };
  const context={document:{getElementById:get,querySelectorAll:()=>[],querySelector:()=>null,createElement:node,createElementNS:node},
    location:{hash:'',origin:'http://127.0.0.1:8766'},CSS:{escape:value=>value},addEventListener(){},
    ResizeObserver:class{observe(){}},AbortController,setTimeout:()=>0,clearTimeout(){},
    fetch:async url=>{calls.push(url);const data=url==='/api/diagnostics'?await diagnostic:responses[url];assert.ok(data,`Unexpected request ${url}`);return {ok:true,status:200,json:async()=>data};}};
  vm.createContext(context);
  for(const filename of ['evaluation.js','app.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/demand_forecast/static',filename),'utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(calls.includes('/api/diagnostics'),'The optional diagnostic starts');
  assert.ok(calls.includes('/api/evidence'),'Evidence starts while diagnostics remain pending');
  assert.ok(calls.includes('/api/forecast'),'Forecast starts while diagnostics remain pending');
  assert.ok(calls.includes('/openapi.json'),'API starts while diagnostics remain pending');
  assert.equal(get('download-forecast').disabled,false,'The forecast completed before the diagnostic');
  // Finish with an empty-data response: its own error stays in the diagnostic region.
  completeDiagnostic({schema_version:1,overall:{n:0}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(get('diagnostics-message').textContent,/No paired/);
  assert.equal(get('init-error').hidden,true);
});
