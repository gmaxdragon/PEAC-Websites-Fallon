"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const banner = $('publicModeBanner');
  try { if (sessionStorage.getItem('peac.bannerDismissed') === '1' && banner) banner.hidden = true; } catch (_) {}
  $('dismissPublicBanner')?.addEventListener('click', () => {
    if (banner) banner.hidden = true;
    try { sessionStorage.setItem('peac.bannerDismissed', '1'); } catch (_) {}
    document.querySelector('.public-brand')?.focus({preventScroll:true});
  });
  let busy=false, pending=null, feedbackPending=null;
  try { pending=JSON.parse(sessionStorage.getItem('peac.lunch.pending')||'null'); } catch (_) {}
  if (pending && (typeof pending!=='object' || !/^[a-zA-Z0-9_-]{16,100}$/.test(pending.key||'') || !/^[a-f0-9]{64}$/.test(pending.fingerprint||''))) pending=null;
  const key=()=>Array.from(crypto.getRandomValues(new Uint8Array(20)),b=>b.toString(16).padStart(2,'0')).join('');
  const hash=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value))),b=>b.toString(16).padStart(2,'0')).join('');
  function status(message,error=false){$('lunchStatus').textContent=message;$('lunchStatus').classList.toggle('error',error);}
  function savePending(){try{if(pending)sessionStorage.setItem('peac.lunch.pending',JSON.stringify(pending));else sessionStorage.removeItem('peac.lunch.pending');}catch(_) {}}
  async function json(path,options={},timeoutMs=18000){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
    try{
      const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...options,signal:controller.signal});
      let data;try{data=await response.json();}catch(_){throw Error('The server response could not be confirmed. Keep your details and retry.');}
      if(!response.ok){const error=Error(data?.error||`Request failed (${response.status}).`);error.status=response.status;throw error;}
      return data;
    }finally{clearTimeout(timer);}
  }
  const form=$('lunchForm');
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!form.reportValidity())return;
    busy=true;$('submitLunchBtn').disabled=true;
    const payload=Object.fromEntries(new FormData(form));payload.consent=payload.consent==='on';
    const fields=$('lunchFields'),wasDisabled=fields.disabled;fields.disabled=true;
    try{
      const fingerprint=await hash(JSON.stringify(payload));
      if(pending&&pending.fingerprint!==fingerprint)throw Error('An earlier request is unconfirmed. Restore its exact details and retry, or ask a coordinator to check it.');
      if(!pending)pending={key:key(),fingerprint};savePending();status('Saving your request...');
      let confirmed=null,lastError;
      for(let attempt=0;attempt<3;attempt++){
        try{
          const data=await json('/api/public/lunch',{method:'POST',headers:{'Content-Type':'application/json','X-PEAC-Client':'1','Idempotency-Key':pending.key},body:JSON.stringify(payload)});
          if(data?.ok!==true || typeof data.reference!=='string' || !/^LB-[A-Z0-9]+$/.test(data.reference))throw Error('The server response could not be confirmed. Keep your details and retry.');
          confirmed=data;break;
        }catch(error){lastError=error;if(error.status>=400&&error.status<500)break;}
        if(attempt<2){status(`Reconnecting. Retrying safely (${attempt+1}/2)...`);await new Promise(resolve=>setTimeout(resolve,900*(attempt+1)));}
      }
      if(!confirmed){
        if(lastError?.status>=400&&lastError.status<500&&![408,409,429].includes(lastError.status)){pending=null;savePending();}
        throw lastError||Error('Your request could not be confirmed.');
      }
      pending=null;savePending();form.reset();form.classList.add('hidden');
      $('lunchReference').textContent=confirmed.reference;$('successMessage').textContent=confirmed.message||'Your request was received.';
      $('lunchSuccess').classList.remove('hidden');$('lunchSuccess').focus();
    }catch(error){status(error.name==='AbortError'?'PEAC could not confirm the response. Retry with the same details; the saved request key prevents duplicates.':error.message,true);}
    finally{busy=false;$('submitLunchBtn').disabled=false;fields.disabled=wasDisabled;}
  });
  let configLoading=false;
  const retry=document.createElement('button');retry.type='button';retry.className='btn light';retry.id='retryPublicConfig';retry.textContent='Retry connection';retry.hidden=true;$('formAvailability').after(retry);
  async function loadConfig(){
    if(configLoading)return;configLoading=true;retry.hidden=true;
    try{
      const c=await json('/api/public/config',{},15000);
      if(!c||typeof c.lunch_enabled!=='boolean'||!/^\d{4}-\d{2}-\d{2}$/.test(c.today||''))throw Error('Invalid configuration');
      $('publicSchoolLabel').textContent=c.school_label;
      if(c.quote){$('publicDailyQuote').textContent=c.quote.text;$('publicQuoteDate').textContent=c.quote.date;}
      $('aboutText').textContent=c.about||'PEAC brings students together through small acts of kindness, shared lunches, and everyday support.';
      $('lunchIntro').textContent=c.lunch_intro;$('privacyNotice').textContent=c.privacy_notice;
      $('lunchDate').min=c.today;const max=new Date(c.today+'T12:00:00');max.setDate(max.getDate()+90);$('lunchDate').max=[max.getFullYear(),String(max.getMonth()+1).padStart(2,'0'),String(max.getDate()).padStart(2,'0')].join('-');
      $('lunchFields').disabled=!c.lunch_enabled;$('formAvailability').textContent=c.lunch_enabled?'Requests are open. Your details go to the private PEAC queue.':'Requests are paused while the PEAC team finishes setup. Please check with your coordinator.';
      if(pending)status('A previous request has an unconfirmed response. Re-enter its exact details and retry, or ask a coordinator to check it first.',true);
    }catch(_){$('lunchFields').disabled=true;$('formAvailability').textContent='PEAC could not check request availability. Retry the connection. Your form has not been sent.';retry.hidden=false;}
    finally{configLoading=false;}
  }
  retry.addEventListener('click',loadConfig);loadConfig();
  $('publicFeedbackBtn')?.addEventListener('click',async()=>{
    const button=$('publicFeedbackBtn'),field=$('publicFeedbackText'),notice=$('publicFeedbackStatus'),message=field.value.trim();
    if(button.disabled)return;if(!message){notice.textContent='Write feedback first.';return;}
    if(feedbackPending&&feedbackPending.message!==message){notice.textContent='An earlier feedback save is unconfirmed. Restore the previous message and retry first.';return;}
    if(!feedbackPending)feedbackPending={key:key(),message};
    button.disabled=true;notice.textContent='Saving feedback...';
    try{
      const data=await json('/api/public/feedback',{method:'POST',headers:{'Content-Type':'application/json','X-PEAC-Client':'1','Idempotency-Key':feedbackPending.key},body:JSON.stringify({message})});
      if(data?.ok!==true||typeof data.id!=='string')throw Error('Feedback could not be confirmed. Retry the same message.');
      feedbackPending=null;if(field.value.trim()===message)field.value='';notice.textContent='Feedback saved privately. Thank you.';
    }catch(error){
      if(error.status>=400&&error.status<500&&![408,409,429].includes(error.status))feedbackPending=null;
      notice.textContent=error.name==='AbortError'?'Feedback could not be confirmed. Retry the same message safely.':error.message;
    }finally{button.disabled=false;}
  });
})();

/* Page-wide theme switch. No network requests, saved preferences or scroll hijacking. */
(() => {
  const root = document.documentElement;
  const boundary = document.getElementById('feedback');
  if (!document.body.classList.contains('public-site') || !boundary) return;
  const chromeColor = document.querySelector('meta[name="theme-color"]');
  let dark = null;
  let queuedFrame = 0;
  let fullHeight = window.innerHeight;
  const deadband = 16;
  boundary.dataset.themeBoundary = 'feedback';
  root.dataset.themeRevision = '2026.10.22.1';

  function isEditing() {
    return document.activeElement?.matches('input,textarea,select,[contenteditable="true"]');
  }

  function syncTheme() {
    queuedFrame = 0;
    // Dialog scroll locks must not change the surrounding theme mid-session.
    if (document.querySelector('dialog[open]')) return;
    const visual = window.visualViewport;
    const height = isEditing() ? fullHeight : (visual?.height || window.innerHeight);
    const offset = isEditing() ? 0 : (visual?.offsetTop || 0);
    const activationLine = offset + Math.min(300, Math.max(120, height * .42));
    const distance = boundary.getBoundingClientRect().top - activationLine;
    const next = dark === null ? distance <= 0 : dark ? distance < deadband : distance <= -deadband;
    if (next === dark) return;
    dark = next;
    root.dataset.peacTheme = dark ? 'dark' : 'light';
    if (chromeColor) chromeColor.content = dark ? '#102f27' : '#f8faf4';
  }

  function schedule() {
    if (!queuedFrame) queuedFrame = requestAnimationFrame(syncTheme);
  }

  function resize() {
    // Do not move the threshold just because a phone's keyboard opens.
    if (!isEditing()) fullHeight = window.innerHeight;
    schedule();
  }

  window.addEventListener('scroll', schedule, { passive:true });
  window.addEventListener('resize', resize, { passive:true });
  window.addEventListener('orientationchange', resize, { passive:true });
  window.addEventListener('pageshow', schedule);
  window.addEventListener('hashchange', schedule);
  window.addEventListener('load', schedule, { once:true });
  window.visualViewport?.addEventListener('resize', resize, { passive:true });
  window.visualViewport?.addEventListener('scroll', schedule, { passive:true });
  document.addEventListener('focusout', schedule);
  document.addEventListener('close', schedule, true);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) schedule(); });
  // News/config loading, form messages and textarea resizing can move the divider.
  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(schedule);
    observer.observe(document.querySelector('.public-shell'));
  }
  document.fonts?.ready.then(schedule);
  syncTheme();
  requestAnimationFrame(() => { root.dataset.themeReady = 'true'; schedule(); });
})();
