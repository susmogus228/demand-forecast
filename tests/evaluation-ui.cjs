'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function fixture(){
  const nodes=new Map(),tables=new Map();
  const $=id=>{if(!nodes.has(id))nodes.set(id,{hidden:false,textContent:'',disabled:false,setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];}});return nodes.get(id);};
  const queue=[];const context={globalThis:{},module:{exports:{}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/demand_forecast/static/evaluation.js'),'utf8'),context);
  const ui=context.module.exports.create({$,fmt:(n,d=3)=>n.toFixed(d),table:(node,heads,rows)=>tables.set(node,{heads,rows}),request:()=>new Promise((resolve,reject)=>queue.push({resolve,reject}))});
  return {ui,$,tables,queue};
}
function response(){return {data:{schema_version:1,selected_model:'ridge',overall:{n:3,model_mae:4,baseline_mae:3,delta_mae:1},loss_counts:{months:1,hours:1,days:1},by_month:[{month:'2012-08',n:3,model_mae:4,baseline_mae:3,delta_mae:1}],by_hour:[{hour:8,horizon:8,n:3,model_mae:4,baseline_mae:3,delta_mae:1}],by_day:[{day:'2012-08-07',n:3,model_mae:4,baseline_mae:3,delta_mae:1}],validation_candidates:[{model:'ridge',n:3,mae:4,rmse:5,selected:true}]}};}
test('reports paired counts, units and signed losses; keeps raw JSON separate',async()=>{
  const f=fixture(),pending=f.ui.load();assert.equal(f.$('diagnostics-retry').disabled,true);
  f.queue[0].resolve(response());await pending;
  assert.equal(f.$('diagnostics-content').hidden,false);
  assert.match(f.$('diagnostics-summary').textContent,/1\/1 months/);
  assert.match(f.$('diagnostics-summary').textContent,/1\/1 target hours/);
  const hourly=f.tables.get(f.$('hour-comparison'));
  assert.equal(hourly.rows[0][0],'08:00 / 8');assert.equal(hourly.rows[0][1],'+1.000 (worse)');
  assert.equal(hourly.heads[1],'Δ MAE');
  assert.equal(hourly.rows[0][2],'4.000');assert.equal(hourly.rows[0][3],'3.000');assert.equal(hourly.rows[0][4],3);
  for(const id of ['overall-comparison','month-comparison','day-comparison']){
    const comparison=f.tables.get(f.$(id));
    assert.equal(comparison.heads[1],'Δ MAE');assert.equal(comparison.rows[0][1],'+1.000 (worse)');
    assert.equal(comparison.heads[4],'Paired hours');
  }
  assert.match(f.$('diagnostics-json').textContent,/schema_version/);
});
test('failed load clears stale content and offers retry',async()=>{
  const f=fixture(),pending=f.ui.load();f.queue[0].reject(new Error('checksum failure'));await pending;
  assert.equal(f.$('diagnostics-content').hidden,true);assert.equal(f.$('diagnostics-retry').disabled,false);
  assert.equal(f.$('diagnostics-message').role,'alert');assert.match(f.$('diagnostics-message').textContent,/checksum failure/);
  const next=f.ui.load();f.queue[1].resolve(response());await next;
  assert.equal(f.$('diagnostics-content').hidden,false);
});
test('late response cannot replace a newer result',async()=>{
  const f=fixture(),first=f.ui.load(),second=f.ui.load();
  f.queue[1].resolve(response());await second;
  f.queue[0].reject(new Error('stale error'));await first;
  assert.equal(f.$('diagnostics-content').hidden,false);assert.doesNotMatch(f.$('diagnostics-message').textContent,/stale/);
});
test('empty or malformed diagnostic shows no invented values',async()=>{
  const f=fixture(),pending=f.ui.load();const empty=response();empty.data.overall.n=0;
  f.queue[0].resolve(empty);await pending;
  assert.equal(f.$('diagnostics-content').hidden,true);assert.match(f.$('diagnostics-message').textContent,/No paired/);
});
