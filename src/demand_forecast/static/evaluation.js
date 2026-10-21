'use strict';
(function(root){
  function create({request,$,table,fmt}){
    let revision=0;
    const signed=value=>`${value>0?'+':''}${fmt(value,3)} (${value>1e-12?'worse':value< -1e-12?'better':'tie'})`;
    function render(data){
      if(data.schema_version!==1||!data.overall?.n||!['by_month','by_hour','by_day','validation_candidates'].every(key=>Array.isArray(data[key])&&data[key].length))throw new Error('No paired diagnostic targets are available. Reproduce diagnostics and retry.');
      const scoreRows=rows=>rows.map(row=>[row.name,signed(row.delta_mae),fmt(row.model_mae,3),fmt(row.baseline_mae,3),row.n]);
      const headers=['Slice','Δ MAE','Model MAE','Baseline MAE','Paired hours'];
      table($('overall-comparison'),headers,scoreRows([{...data.overall,name:'All test hours'}]));
      table($('month-comparison'),headers,scoreRows(data.by_month.map(row=>({...row,name:row.month}))));
      table($('hour-comparison'),['Hour / horizon',...headers.slice(1)],scoreRows(data.by_hour.map(row=>({...row,name:`${String(row.hour).padStart(2,'0')}:00 / ${row.horizon}`}))));
      table($('day-comparison'),headers,scoreRows(data.by_day.map(row=>({...row,name:row.day}))));
      const names={seasonal_naive:'Seasonal naive with fallback',ridge:'Ridge regression',hist_gradient_boosting:'Histogram gradient boosting'};
      table($('candidate-comparison'),['Validation candidate','Observed hours','MAE · rentals/h','RMSE · rentals/h','Decision'],data.validation_candidates.map(row=>[names[row.model]||row.model,row.n,fmt(row.mae,3),fmt(row.rmse,3),row.selected?'Selected on validation':'Not selected']));
      $('diagnostics-summary').textContent=`${data.selected_model} loses to the baseline on ${data.loss_counts.months}/${data.by_month.length} months, ${data.loss_counts.hours}/${data.by_hour.length} target hours, and ${data.loss_counts.days}/${data.by_day.length} test days. ${data.overall.n.toLocaleString('en-US')} paired observed targets; the overall gain does not apply to every slice.`;
      $('diagnostics-json').textContent=JSON.stringify(data,null,2);
    }
    async function load(){
      const current=++revision;
      $('diagnostics-retry').disabled=true;$('diagnostics-content').hidden=true;
      $('diagnostics-region').setAttribute('aria-busy','true');
      $('diagnostics-message').setAttribute('role','status');$('diagnostics-message').textContent='Loading paired, hash-checked comparisons…';
      try{
        const response=await request('/api/diagnostics');if(current!==revision)return;
        render(response.data);$('diagnostics-content').hidden=false;
        $('diagnostics-message').textContent='Verified frozen prediction lineage. No retraining or test-based model selection.';
      }catch(error){if(current!==revision)return;$('diagnostics-content').hidden=true;$('diagnostics-message').setAttribute('role','alert');$('diagnostics-message').textContent=`Comparison unavailable: ${error.message||'local service error'}. Retry loading below.`;
      }finally{if(current===revision){$('diagnostics-retry').disabled=false;$('diagnostics-region').removeAttribute('aria-busy');}}
    }
    return {load};
  }
  root.ForecastEvaluation={create};
  if(typeof module!=='undefined'&&module.exports)module.exports={create};
})(globalThis);
