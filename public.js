"use strict";
(() => {
  const $ = id => document.getElementById(id);
  let busy=false, pending=null;
  try { pending=JSON.parse(sessionStorage.getItem('peac.lunch.pending')||'null'); } catch (_) {}
  function status(message,error=false){$('lunchStatus').textContent=message;$('lunchStatus').classList.toggle('error',error);}
  function newKey(){return Array.from(crypto.getRandomValues(new Uint8Array(20)),b=>b.toString(16).padStart(2,'0')).join('');}
  async function hash(value){const data=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value));return Array.from(new Uint8Array(data),x=>x.toString(16).padStart(2,'0')).join('');}
  const form=$('lunchForm');
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(busy||!form.reportValidity())return;
    busy=true;$('submitLunchBtn').disabled=true;
    const f=new FormData(form);const payload=Object.fromEntries(f);payload.consent=f.get('consent')==='on';
    try {
      const fingerprint=await hash(JSON.stringify(payload));
      if(pending&&pending.fingerprint!==fingerprint)throw new Error('An earlier request has not been confirmed. Restore the same details and retry, or ask a coordinator to check before creating another request.');
      if(!pending)pending={key:newKey(),fingerprint};
      try{sessionStorage.setItem('peac.lunch.pending',JSON.stringify(pending));}catch(_){}
      status('Saving your request...');
      const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);let r,data;
      try{r=await fetch('/api/public/lunch',{method:'POST',headers:{'Content-Type':'application/json','X-PEAC-Client':'1','Idempotency-Key':pending.key},body:JSON.stringify(payload),credentials:'same-origin',signal:controller.signal});data=await r.json();}
      finally{clearTimeout(timer);}
      if(!r.ok){
        if(r.status>=400&&r.status<500&&r.status!==409){pending=null;try{sessionStorage.removeItem('peac.lunch.pending');}catch(_){}}
        throw new Error(data.error||'Unable to save. Please keep these details and retry.');
      }
      pending=null;try{sessionStorage.removeItem('peac.lunch.pending');}catch(_){}
      form.reset();form.classList.add('hidden');$('lunchReference').textContent=data.reference;$('successMessage').textContent=data.message;
      $('lunchSuccess').classList.remove('hidden');$('lunchSuccess').focus();
    }catch(error){status(error.name==='AbortError'?'The response timed out. Keep the same details and press Send again to check the original request without creating a duplicate.':error.message,true);}
    finally{busy=false;$('submitLunchBtn').disabled=false;}
  });
  fetch('/api/public/config',{cache:'no-store'}).then(async r=>{if(!r.ok)throw Error('Unavailable');return r.json();}).then(c=>{
    $('publicSchoolLabel').textContent=c.school_label;
    if(c.quote){$('publicDailyQuote').textContent=c.quote.text;$('publicQuoteDate').textContent=c.quote.date;}
    $('aboutText').textContent=c.about||'The PEAC team is preparing this section. Check back for our story, mission, and programs.';
    $('lunchIntro').textContent=c.lunch_intro;$('privacyNotice').textContent=c.privacy_notice;
    $('lunchDate').min=c.today;const max=new Date(c.today+'T12:00:00');max.setDate(max.getDate()+90);$('lunchDate').max=[max.getFullYear(),String(max.getMonth()+1).padStart(2,'0'),String(max.getDate()).padStart(2,'0')].join('-');
    $('lunchFields').disabled=!c.lunch_enabled;$('formAvailability').textContent=c.lunch_enabled?'Requests are open. Your details go to the private PEAC queue.':'Requests are paused while the PEAC team finishes setup. Please check with your coordinator.';
    if(pending)status('A previous request has an unconfirmed response. Re-enter its exact details to reconcile it, or ask a coordinator to check it first.',true);
  }).catch(()=>{$('formAvailability').textContent='This preview is not connected. Open the page through the PEAC server; no request has been sent.';});
  $('motionToggle').addEventListener('click',()=>{const off=document.documentElement.dataset.motion!=='off';document.documentElement.dataset.motion=off?'off':'on';$('motionToggle').setAttribute('aria-pressed',String(off));$('motionToggle').textContent=off?'Motion reduced':'Reduce motion';});
})();
