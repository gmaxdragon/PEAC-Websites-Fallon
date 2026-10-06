"use strict";
const login=document.getElementById('loginForm'),signup=document.getElementById('signupForm');
function show(which){login.classList.toggle('hidden',which!=='login');signup.classList.toggle('hidden',which!=='signup');}
document.getElementById('showSignup').addEventListener('click',()=>show('signup'));
document.getElementById('showLogin').addEventListener('click',()=>show('login'));
login.addEventListener('submit',async e=>{e.preventDefault();const button=document.getElementById('loginButton'),status=document.getElementById('loginStatus');if(button.disabled||!login.reportValidity())return;button.disabled=true;status.textContent='Signing in...';status.classList.remove('error');try{const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json','X-PEAC-Client':'1'},credentials:'same-origin',body:JSON.stringify(Object.fromEntries(new FormData(login)))});const data=await r.json();if(!r.ok)throw Error(data.error||'Sign-in failed.');login.reset();location.assign('/console');}catch(err){status.textContent=err.message;status.classList.add('error');}finally{button.disabled=false;}});
signup.addEventListener('submit',async e=>{
  e.preventDefault();
  const button=document.getElementById('signupButton'),status=document.getElementById('signupStatus'),success=document.getElementById('signupSuccess');
  success.classList.add('hidden');
  if(button.disabled)return;
  if(!signup.reportValidity()){
    status.textContent='Check the highlighted fields. Usernames need at least 3 valid characters and passwords need at least 12 characters.';
    status.classList.add('error');
    return;
  }
  button.disabled=true;status.textContent='Sending request...';status.classList.remove('error');
  let sent=false;
  try{
    const payload=Object.fromEntries(new FormData(signup));payload.username=(payload.username||'').trim().toLowerCase();
    const r=await fetch('/api/auth/signup',{method:'POST',headers:{'Content-Type':'application/json','X-PEAC-Client':'1'},credentials:'same-origin',body:JSON.stringify(payload)});
    const raw=await r.text();let data={};try{data=raw?JSON.parse(raw):{};}catch(_){}
    if(!r.ok)throw Error(data.error||'Sign-up request failed.');
    sent=true;signup.reset();status.textContent='';success.classList.remove('hidden');
    success.innerHTML='<strong>Request received.</strong><br>PEACADMIN has been notified. Your account will work after it is approved.';
    button.textContent='Request received';button.disabled=true;
    Array.from(signup.elements).forEach(el=>{if(el!==document.getElementById('showLogin')&&el!==button)el.disabled=true;});
  }catch(err){
    status.textContent=err.message;status.classList.add('error');
  }finally{
    if(!sent)button.disabled=false;
  }
});
