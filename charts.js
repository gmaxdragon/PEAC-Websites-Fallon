/* Pure date/filter helpers shared by the UI and Node regression tests. */
"use strict";
(function(root){
  const DAY=86400000;
  const stamp=s=>Date.parse(`${s}T00:00:00Z`);
  const iso=n=>new Date(n).toISOString().slice(0,10);
  function weekOf(s){const n=stamp(s),d=new Date(n).getUTCDay();return iso(n-((d+6)%7)*DAY);}
  function dateRange(end,group,span){
    const n=Math.max(1,Math.floor(Number(span)||1));
    return {start:iso(group==='weekly'?stamp(weekOf(end))-(n-1)*7*DAY:stamp(end)-(n-1)*DAY),end};
  }
  function select(entries,options){
    return entries.filter(r=>(!options.start||r.date>=options.start)&&(!options.end||r.date<=options.end)&&(options.grade==='all'||!options.grade||r.grade===options.grade));
  }
  function aggregate(entries,options){
    const rows=new Map();
    for(const r of select(entries,options)){
      const label=options.group==='weekly'?weekOf(r.date):r.date;
      if(!rows.has(label))rows.set(label,{week:label,count:0,trash_count:0,lunch_buddies:0,dates:new Set()});
      const item=rows.get(label);item.count+=Number(r.count||0);item.trash_count+=Number(r.trash_count||0);item.lunch_buddies+=Number(r.lunch_buddies||0);item.dates.add(r.date);
    }
    return [...rows.values()].sort((a,b)=>a.week.localeCompare(b.week)).map(r=>({...r,dates:[...r.dates]}));
  }
  const SERIES={
    count:{key:'count',label:'Verified compliments',color:'#237c51'},
    trash_count:{key:'trash_count',label:'Trash',color:'#71982f'},
    lunch_buddies:{key:'lunch_buddies',label:'Lunch Buddies',color:'#7b6fb0'}
  };
  function metricKeys(metricOrMetrics){
    if(Array.isArray(metricOrMetrics))return [...new Set(metricOrMetrics.filter(k=>SERIES[k]))];
    if(metricOrMetrics==='both')return ['count','trash_count'];
    if(metricOrMetrics==='total')return ['count','trash_count'];
    if(SERIES[metricOrMetrics])return [metricOrMetrics];
    return ['count'];
  }
  function measures(metricOrMetrics){return metricKeys(metricOrMetrics).map(k=>SERIES[k]);}
  const value=(r,k)=>k==='total'?Number(r.count||0)+Number(r.trash_count||0):Number(r[k]||0);
  function pie(entries,options){
    const picked=select(entries,options),keys=metricKeys(options.metrics||options.metric);
    if(options.split==='type')return keys.map(k=>({
      label:SERIES[k].label,
      value:picked.reduce((n,r)=>n+value(r,k),0),
      color:SERIES[k].color
    })).filter(r=>r.value>0);
    const colors=['#237c51','#64ae73','#aedc8b','#dceab0'];
    return ['8','7','6','unassigned'].map((g,i)=>({label:g==='unassigned'?'Unassigned':`Grade ${g}`,color:colors[i],
      value:picked.filter(r=>r.grade===g).reduce((n,r)=>n+keys.reduce((sum,k)=>sum+value(r,k),0),0)
    })).filter(r=>r.value>0);
  }
  function niceMax(n){if(n<=0)return 1;const raw=n/4,scale=10**Math.floor(Math.log10(raw));const step=[1,2,2.5,5,10].find(v=>v*scale>=raw)*scale;return Math.ceil(n/step)*step;}
  const api={DAY,stamp,iso,weekOf,dateRange,select,aggregate,measures,value,pie,niceMax};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.PEACCharts=api;
})(typeof window!=='undefined'?window:globalThis);
