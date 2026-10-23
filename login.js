"use strict";
async function accessRequest(path,payload){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
 try{
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-PEAC-Client':'1'},credentials:'same-origin',body:JSON.stringify(payload),signal:controller.signal});
  let data;try{data=await response.json();}catch(_){throw Error('The server response could not be confirmed. Please retry.');}
  if(!response.ok)throw Error(data?.error||'The request failed. Please retry.');
  return data;
 }catch(error){if(error.name==='AbortError')throw Error('The connection timed out. Please retry.');throw error;}finally{clearTimeout(timer);}
}

const login=document.getElementById('loginForm'),signup=document.getElementById('signupForm');
function show(which){login.classList.toggle('hidden',which!=='login');signup.classList.toggle('hidden',which!=='signup');}
document.getElementById('showSignup').addEventListener('click',()=>show('signup'));
document.getElementById('showLogin').addEventListener('click',()=>show('login'));
login.addEventListener('submit',async e=>{e.preventDefault();const button=document.getElementById('loginButton'),status=document.getElementById('loginStatus');if(button.disabled||!login.reportValidity())return;button.disabled=true;status.textContent='Signing in...';status.classList.remove('error');try{const data=await accessRequest('/api/auth/login',Object.fromEntries(new FormData(login)));if(!data?.user||typeof data.csrf!=='string')throw Error('Sign-in was not confirmed. Please retry.');login.reset();location.assign('/console');}catch(err){status.textContent=err.message;status.classList.add('error');}finally{button.disabled=false;}});
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
    const data=await accessRequest('/api/auth/signup',payload);
    if(data?.ok!==true||data.status!=='pending'||typeof data.request_id!=='string')throw Error('The access request could not be confirmed. Please retry.');
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
