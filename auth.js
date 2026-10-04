"use strict";
(() => {
  const state={user:null,csrf:null};
  const ready=fetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'}).then(async r=>{
    if(!r.ok)throw Error('Unable to verify your sign-in.');const s=await r.json();
    if(!s.user){location.replace('/login');throw Error('Sign in required.');}
    Object.assign(state,s);return s;
  });
  ready.catch(()=>{});
  function key(){return Array.from(crypto.getRandomValues(new Uint8Array(18)),b=>b.toString(16).padStart(2,'0')).join('');}
  const pending=new Map();
  async function api(path,method='GET',payload,requestKey){
    await ready;const opts={method,credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}};
    if(method!=='GET'){Object.assign(opts.headers,{'Content-Type':'application/json','X-PEAC-Client':'1','X-CSRF-Token':state.csrf,'Idempotency-Key':requestKey||key()});opts.body=JSON.stringify(payload||{});}
    const c=new AbortController();opts.signal=c.signal;const timer=setTimeout(()=>c.abort(),30000);
    try{const r=await fetch(path,opts);let data;try{data=await r.json();}catch(_){throw Error('Unconfirmed response. Keep the original values and retry.');}
      if(r.status===401){location.replace('/login');throw Error('Your session ended. Sign in again.');}
      if(!r.ok){const e=Error(data.error||`Request failed (${r.status}).`);e.status=r.status;throw e;}return data;
    }finally{clearTimeout(timer);}
  }
  async function mutate(slot,path,method,payload){
    const sig=JSON.stringify([path,method,payload]);let p=pending.get(slot);
    if(p&&p.sig!==sig)throw Error('The previous save is unconfirmed. Restore the same values and retry before changing them.');
    if(!p){p={sig,key:key()};pending.set(slot,p);}
    try{const r=await api(path,method,payload,p.key);pending.delete(slot);return r;}
    catch(e){if(e.status>=400&&e.status<500)pending.delete(slot);throw e;}
  }
  window.PEACSession={state,ready,api,mutate,key};
})();
