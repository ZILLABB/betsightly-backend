import test from 'node:test';
import assert from 'node:assert/strict';
import handler from '../api/proxy.js';

const HOST = 'betsightly-admin-preview.vercel.app';
const BACKEND = 'https://betsightly-api.onrender.com';
process.env.ADMIN_BACKEND_ORIGIN = BACKEND;
const originalFetch = globalThis.fetch;
const req = (path,method='GET',body=undefined,origin=undefined) => ({
  url: '/api/proxy?path=' + encodeURIComponent(path),
  headers: {host:HOST, ...(origin === undefined ? {} : {origin}),cookie:'bs_admin=signed-test'},
  method,body
});
function response(){
  return {
    code:200,headers:{},body:null,
    setHeader(k,v){this.headers[k.toLowerCase()]=v;return this;},
    status(n){this.code=n;return this;},
    json(value){this.body=value;return this;},
    send(value){this.body=value;return this;}
  };
}
test('rejects unlisted API routes without contacting the backend',async()=>{
  globalThis.fetch=()=>{throw Error('should not fetch')};
  try{
    const r=response();await handler(req('../../admin/key'),r);
    assert.equal(r.code,404);
    const rr=response();await handler(req('manual-tiers/assistant/publish','POST',{},'https://'+HOST),rr);
    assert.equal(rr.code,404);
  }finally{globalThis.fetch=originalFetch}
});
test('blocks a state-changing request with missing or foreign origin',async()=>{
  globalThis.fetch=()=>{throw Error('should not fetch')};
  try{
    const r=response();await handler(req('manual-tiers/publish','POST',{tier:'2_odds'}),r);
    assert.equal(r.code,403);
    const rr=response();await handler(req('manual-tiers/publish','POST',{},'https://evil.example'),rr);
    assert.equal(rr.code,403);
  }finally{globalThis.fetch=originalFetch}
});
test('proxies backend GET session read with cookie and disables caching',async()=>{
  let seen;
  globalThis.fetch=async(url,opts)=>{
    seen={url:String(url),opts};return new Response(JSON.stringify({ok:true,admin:'admin'}),{status:200,headers:{'content-type':'application/json'}});
  };
  try{
    const r=response();await handler(req('admin/me'),r);
    assert.equal(r.code,200);
    assert.equal(JSON.parse(r.body).ok,true);
    assert.equal(seen.url,BACKEND+'/api/growth/admin/me');
    assert.equal(seen.opts.headers.cookie,'bs_admin=signed-test');
    assert.equal(r.headers['cache-control'],'no-store');
  }finally{globalThis.fetch=originalFetch}
});
test('forwards verified same-origin mutation with backend origin, without retrying',async()=>{
  let calls=0;let observed;
  globalThis.fetch=async(url,opts)=>{
    calls++;observed={url:String(url),opts};
    return new Response(JSON.stringify({share_code:'TEST123'}),{status:200,headers:{'content-type':'application/json','set-cookie':'bs_admin=test; Secure; HttpOnly; SameSite=Strict; Path=/'}});
  };
  try{
    const r=response();
    await handler(req('manual-tiers/publish','POST',{tier:'2_odds',lines:'123,home_win'},'https://'+HOST),r);
    assert.equal(calls,1);assert.equal(r.code,200);
    assert.equal(observed.opts.headers.origin,BACKEND);
    assert.equal(JSON.parse(observed.opts.body).tier,'2_odds');
    assert.match(r.headers['set-cookie'],/SameSite=Strict/);
  }finally{globalThis.fetch=originalFetch}
});
test('reports an interrupted POST as unknown without retrying',async()=>{
  let calls=0;globalThis.fetch=async()=>{calls++;throw Error('network 502')};
  try{
    const r=response();await handler(req('manual-tiers/publish','POST',{tier:'2_odds'},'https://'+HOST),r);
    assert.equal(calls,1);assert.equal(r.code,502);
    assert.match(r.body.detail,/check saved tickets/i);
  }finally{globalThis.fetch=originalFetch}
});

test('forwards login session cookie from backend without surfacing it in JSON',async()=>{
 let seen;let calls=0;
 globalThis.fetch=async(url,opts)=>{
  calls++;seen={url:String(url),opts};
  return new Response(JSON.stringify({ok:true,expires_in:3600}),{
   status:200,headers:{'content-type':'application/json','set-cookie':'bs_admin=signed-session; Secure; HttpOnly; SameSite=Strict; Path=/'}
  });
 };
 try{
  const r=response();
  await handler(req('admin/login','POST',{password:'fake-test-only-secret'},'https://'+HOST),r);
  assert.equal(r.code,200);
  assert.equal(calls,1);
  assert.equal(seen.url,BACKEND+'/api/growth/admin/login');
  assert.deepEqual(JSON.parse(seen.opts.body),{password:'fake-test-only-secret'});
  assert.match(r.headers['set-cookie'],/HttpOnly/);
  assert.match(r.headers['set-cookie'],/SameSite=Strict/);
  assert.doesNotMatch(r.body,/fake-test-only-secret|signed-session/);
 }finally{globalThis.fetch=originalFetch}
});
test('a failed admin authentication is forwarded as 401, never transformed into success',async()=>{
 let calls=0;
 globalThis.fetch=async()=>{calls++;return new Response(JSON.stringify({detail:'Not signed in.'}),{status:401,headers:{'content-type':'application/json'}})};
 try{
  const r=response();await handler(req('manual-tiers'),r);
  assert.equal(r.code,401);assert.equal(calls,1);
  assert.equal(JSON.parse(r.body).detail,'Not signed in.');
 }finally{globalThis.fetch=originalFetch}
});
test('misconfigured upstream fails closed before contacting external domains',async()=>{
 const previous=process.env.ADMIN_BACKEND_ORIGIN;let calls=0;
 process.env.ADMIN_BACKEND_ORIGIN='https://evil.example.com';
 globalThis.fetch=async()=>{calls++;throw Error('no outbound call allowed')};
 try{
  const r=response();await handler(req('admin/config'),r);
  assert.equal(r.code,503);assert.equal(calls,0);
 }finally{process.env.ADMIN_BACKEND_ORIGIN=previous;globalThis.fetch=originalFetch}
});

test('normalizes a raw JSON login body without changing the password bytes',async()=>{
 let seen;globalThis.fetch=async(url,opts)=>{
  seen={url:String(url),opts};
  return new Response(JSON.stringify({detail:'Incorrect password.'}),{status:401,headers:{'content-type':'application/json'}});
 };
 try{
  const textPassword=' unchanged +unicode• ';
  const r=response();
  await handler(req('admin/login','POST',JSON.stringify({password:textPassword}),'https://'+HOST),r);
  assert.equal(r.code,401);
  assert.equal(JSON.parse(seen.opts.body).password,textPassword);
  assert.equal(JSON.parse(r.body).detail,'Incorrect password.');
 }finally{globalThis.fetch=originalFetch}
});
test('normalizes a Buffer login body without substituting an empty password',async()=>{
 let seen;globalThis.fetch=async(url,opts)=>{
  seen=JSON.parse(opts.body);
  return new Response(JSON.stringify({ok:true}),{status:200,headers:{'content-type':'application/json'}});
 };
 try{
  const r=response();
  await handler(req('admin/login','POST',Buffer.from(JSON.stringify({password:'sample-not-a-secret'})),'https://'+HOST),r);
  assert.equal(r.code,200);
  assert.equal(seen.password,'sample-not-a-secret');
 }finally{globalThis.fetch=originalFetch}
});
test('missing or malformed login JSON is rejected locally and never sent upstream',async()=>{
 let calls=0;globalThis.fetch=async()=>{calls++;throw Error('should not call upstream')};
 try{
  for(const body of [undefined,'{broken',{}, {password:''},['x']]){
   const r=response();
   await handler(req('admin/login','POST',body,'https://'+HOST),r);
   assert.equal(r.code,400);
  }
  assert.equal(calls,0);
 }finally{globalThis.fetch=originalFetch}
});

test('forwards read-only price inspection without reclassifying as publication',async()=>{
 let calls=0;let path;let body;
 globalThis.fetch=async(url,opts)=>{
  calls++;path=String(url);body=JSON.parse(opts.body);
  return new Response(JSON.stringify({
   status:'INSPECTION_ONLY',publish_ready:false,booking_code_created:false,
   games:[{market:'home_win',odds:1.6}]
  }),{status:200,headers:{'content-type':'application/json'}});
 };
 try {
  const res=response();
  await handler(req('manual-tiers/inspect','POST',
    {tier:'10_odds',lines:'52587,home_win'},'https://'+HOST),res);
  assert.equal(calls,1);
  assert.equal(res.code,200);
  assert.equal(path,BACKEND+'/api/growth/manual-tiers/inspect');
  assert.equal(body.tier,'10_odds');
  assert.equal(JSON.parse(res.body).publish_ready,false);
  assert.equal(JSON.parse(res.body).booking_code_created,false);
 }finally{globalThis.fetch=originalFetch}
});


test('private jackpot routes are not accessible as GET and reject foreign-origin mutation',async()=>{
 globalThis.fetch=()=>{throw Error('must not contact upstream')};
 try {
   const get=response();await handler(req('private-jackpot/candidates','GET'),get);
   assert.equal(get.code,404);
   const foreign=response();await handler(req('private-jackpot/book','POST',{selection_ids:['pick1']},'https://evil.example'),foreign);
   assert.equal(foreign.code,403);
 }finally{globalThis.fetch=originalFetch}
});

test('private jackpot POSTs preserve the signed admin cookie and exact selected IDs',async()=>{
 let calls=[];
 globalThis.fetch=async(url,opts)=>{
   calls.push({url:String(url),opts});
   return new Response(JSON.stringify({status:'BELOW_TARGET',share_code:null}),{status:200,headers:{'content-type':'application/json'}});
 };
 try {
   const origin='https://'+HOST;
   const candidates=response();await handler(req('private-jackpot/candidates','POST',{horizon:'today'},origin),candidates);
   const book=response();await handler(req('private-jackpot/book','POST',{selection_ids:['pick1','pick2'],target_odds:100000},origin),book);
   assert.equal(candidates.code,200);assert.equal(book.code,200);
   assert.equal(calls.length,2);
   assert.equal(calls[0].url,BACKEND+'/api/growth/private-jackpot/candidates');
   assert.equal(calls[1].url,BACKEND+'/api/growth/private-jackpot/book');
   assert.equal(calls[1].opts.headers.cookie,'bs_admin=signed-test');
   assert.equal(calls[1].opts.headers.origin,BACKEND);
   assert.deepEqual(JSON.parse(calls[1].opts.body).selection_ids,['pick1','pick2']);
 }finally{globalThis.fetch=originalFetch}
});

test('auto optimizer only accepts authorized admin POST, never GET',async()=>{
 const previous=globalThis.fetch;
 globalThis.fetch=()=>{throw Error('request must be rejected by proxy before upstream')};
 try{
  const get=response();await handler(req('private-jackpot/auto-book','GET'),get);
  assert.equal(get.code,404);
  const foreign=response();await handler(req('private-jackpot/auto-book','POST',{target_odds:100000},'https://evil.invalid'),foreign);
  assert.equal(foreign.code,403);
 }finally{globalThis.fetch=previous}
});

test('auto optimizer forwards explicit constraints to backend with session cookie',async()=>{
 const previous=globalThis.fetch;const seen=[];
 globalThis.fetch=async(url,opts)=>{
  seen.push({url:String(url),opts});
  return new Response(JSON.stringify({status:'UNREACHABLE',share_code:null}),{status:200,headers:{'content-type':'application/json'}});
 };
 try{
  const host='https://'+HOST;
  const target=response();
  await handler(req('private-jackpot/auto-book','POST',{target_odds:100000,max_legs:50,horizon:'7_days',market_style:'all'},host),target);
  assert.equal(target.code,200);
  assert.equal(seen[0].url,BACKEND+'/api/growth/private-jackpot/auto-book');
  assert.equal(seen[0].opts.headers.cookie,'bs_admin=signed-test');
  assert.equal(JSON.parse(seen[0].opts.body).max_legs,50);
  const preview=response();
  await handler(req('private-jackpot/optimize','POST',{target_odds:100000},host),preview);
  assert.equal(preview.code,200);
 }finally{globalThis.fetch=previous}
});

test('pasted fixture preview and bookmaker booking are signed-admin-only POST routes',async()=>{
 const previous=globalThis.fetch;
 globalThis.fetch=()=>{throw Error('request should have been rejected before upstream')};
 try{
  for(const endpoint of ['private-jackpot/paste-preview','private-jackpot/paste-book','private-jackpot/market-catalog']){
   const forbidden=response();await handler(req(endpoint,'GET'),forbidden);
   assert.equal(forbidden.code,404);
   const hostile=response();await handler(req(endpoint,'POST',{fixtures_text:'A vs B'},'https://malicious.invalid'),hostile);
   assert.equal(hostile.code,403);
  }
 }finally{globalThis.fetch=previous}
});

test('paste preview forwards exact fixture text without changing it',async()=>{
 const previous=globalThis.fetch;let seen=[];
 globalThis.fetch=async(url,opts)=>{
  seen.push({url:String(url),opts});
  return new Response(JSON.stringify({status:'UNREACHABLE',matched:[],unmatched:[]}),{status:200,headers:{'content-type':'application/json'}});
 };
 try{
  const fixtureText='Dinamo Zagreb vs NEC Nijmegen\\nBraga vs Gent';
  const payload={fixtures_text:fixtureText,target_odds:100000,horizon:'today'};
  for(const name of ['private-jackpot/paste-preview','private-jackpot/paste-book']){
   const resp=response();await handler(req(name,'POST',payload,'https://'+HOST),resp);
   assert.equal(resp.code,200);
  }
  assert.equal(seen.length,2);
  assert.equal(seen[0].url,BACKEND+'/api/growth/private-jackpot/paste-preview');
  assert.equal(seen[1].url,BACKEND+'/api/growth/private-jackpot/paste-book');
  assert.equal(seen[0].opts.headers.cookie,'bs_admin=signed-test');
  assert.equal(JSON.parse(seen[0].opts.body).fixtures_text,fixtureText);
 }finally{globalThis.fetch=previous}
});


test('private jackpot 502 from Render returns small actionable JSON, not HTML',async()=>{
 const oldFetch=globalThis.fetch;const oldLog=console.error;
 console.error=()=>{};
 globalThis.fetch=async()=>new Response('<html>'+('x'.repeat(223000))+'</html>',{
   status:502,headers:{'content-type':'text/html'}
 });
 try {
   const out=response();
   await handler(req('private-jackpot/paste-preview','POST',{
    fixtures_text:'Hoffenheim vs Lyon | Home win',
    target_odds:100000,selection_mode:'bookmaker_only'
   },'https://'+HOST),out);
   assert.equal(out.code,502);
   assert.match(out.headers['content-type']||'application/json',/json/i);
   assert.match((typeof out.body==='string'?JSON.parse(out.body):out.body).detail,/backend returned HTTP 502/i);
   assert.ok(JSON.stringify(out.body).length<600);
 }finally{globalThis.fetch=oldFetch;console.error=oldLog;}
});

test('private jackpot network failures never trigger automatic POST retries',async()=>{
 const oldFetch=globalThis.fetch;const oldLog=console.error;let count=0;
 console.error=()=>{};
 globalThis.fetch=async()=>{count++;throw new Error('ECONNRESET')};
 try{
  const out=response();
  await handler(req('private-jackpot/paste-book','POST',{
    fixtures_text:'Hoffenheim vs Lyon | Home win'
  },'https://'+HOST),out);
  assert.equal(count,1);
  assert.equal(out.code,502);
  assert.match((typeof out.body==='string'?JSON.parse(out.body):out.body).detail,/Do not repeat Generate Code/i);
 }finally{globalThis.fetch=oldFetch;console.error=oldLog}
});
