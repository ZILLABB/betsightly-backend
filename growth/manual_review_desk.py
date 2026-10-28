"""Self-contained authenticated manual-settlement review desk.

All fixture data is rendered with textContent, never HTML interpolation.
Uses same-origin, admin-session-protected API calls and no external scripts.
"""


def page() -> str:
    return r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; connect-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'">
<title>BetSightly · Settlement Evidence Desk</title>
<style>
:root{color-scheme:dark;--navy:#071d30;--panel:#102b42;--panel2:#153a53;--border:#315166;--text:#ecf3f5;--muted:#9bb4c3;--blue:#5fb6d1}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(145deg,#061421,#10324a);color:var(--text);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh}
main{max-width:1320px;margin:auto;padding:28px 22px 60px}.heading{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;flex-wrap:wrap}
h1{font-size:32px;letter-spacing:-.8px;margin:4px 0}h2{font-size:18px;letter-spacing:-.3px;margin:0 0 12px}.eyebrow{font-size:12px;letter-spacing:2px;font-weight:800;color:var(--blue)}.sub{color:var(--muted);max-width:700px;margin:0}
.grid{display:grid;grid-template-columns: minmax(0,1.5fr) minmax(320px,1fr);gap:20px;margin-top:28px}
.card{background:rgba(16,43,66,.94);border:1px solid var(--border);border-radius:16px;padding:20px;box-shadow:0 12px 28px #07121b40}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.stat{border:1px solid var(--border);border-radius:10px;padding:12px 14px;min-width:118px;background:#15364e}.stat strong{display:block;font-size:24px}.stat small{color:var(--muted)}
button{font:inherit;font-weight:700;cursor:pointer;border-radius:9px;padding:10px 14px;border:1px solid #4b7c95;background:#214b64;color:white}
button:hover{background:#2a6383}button.primary{background:#246d90;border-color:#2a87aa}button:disabled{opacity:.5;cursor:not-allowed}
.controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:16px 0}
input,textarea{font:inherit;color:var(--text);background:#0a2337;border:1px solid #47718a;border-radius:9px;padding:10px 12px;width:100%}
textarea{resize:vertical;min-height:100px}label{display:block;margin:13px 0 6px;color:#d9e7ee;font-weight:600}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.event{display:block;text-align:left;width:100%;padding:13px;border:1px solid var(--border);background:#0b2a40;border-radius:10px;margin-top:8px;font-weight:400}
.event:focus,.event.sel{outline:2px solid var(--blue);background:#16425d}.event b{display:block}.event small{color:var(--muted)}
.muted{color:var(--muted)}.alert{border:1px solid #8b714b;background:#463d28;border-radius:9px;padding:11px 12px;margin-top:16px}
.notice{min-height:24px;margin:14px 0;white-space:pre-wrap}.error{color:#ffb9af}.ok{color:#9ee2bf}
.sep{border-top:1px solid var(--border);margin:20px 0}.check{display:flex;align-items:flex-start;gap:9px;margin-top:12px}.check input{width:auto;margin-top:5px}
#approval{display:none}#selected{font-size:13px;border-left:3px solid var(--blue);padding:9px 12px;background:#0b293f;margin-bottom:14px}
.topright{display:flex;gap:12px;align-items:center}.badge{padding:5px 10px;border-radius:99px;background:#294b61;color:#badced;font-size:11px;font-weight:800}
@media(max-width:880px){.grid{grid-template-columns:1fr}main{padding:20px 14px}h1{font-size:25px}}
</style>
</head>
<body>
<main>
<div class="heading">
<div><div class="eyebrow">BET SIGHTLY / PROTECTED OPERATIONS</div><h1>Settlement Evidence Desk</h1>
<p class="sub">Recover unresolved manual results with an official match report, exact SportyBet event identity and a second explicit approval. Booking codes and model metrics remain separate.</p></div>
<div class="topright"><span class="badge">ADMIN ONLY</span><button id="refresh">Refresh records</button></div>
</div>
<div class="stats">
<div class="stat"><small>Pending legs</small><strong id="pending">—</strong></div>
<div class="stat"><small>Overdue 48h</small><strong id="overdue">—</strong></div>
<div class="stat"><small>Unique events</small><strong id="unique">—</strong></div>
</div>
<div class="grid">
<section class="card">
<h2>Unresolved matches</h2>
<p class="muted">Select the exact stored fixture. Nothing can be marked won or lost by selecting it.</p>
<div class="controls"><input id="filter" placeholder="Filter by country, league, team, ID or date" aria-label="Filter unresolved fixtures"><span id="shown" class="muted"></span></div>
<div id="events" role="list" aria-live="polite"></div>
</section>
<section class="card">
<h2>Submit official 90-minute evidence</h2>
<div id="selected">Choose an unresolved match on the left.</div>
<form id="proposal">
<div class="two"><div><label for="hs">Home goals</label><input type="number" id="hs" min="0" max="30" required></div>
<div><label for="as">Away goals</label><input type="number" id="as" min="0" max="30" required></div></div>
<label for="url">Official result URL</label><input type="url" id="url" placeholder="https://official-league.example/match/…" required>
<label for="note">Evidence verification note</label><textarea id="note" minlength="45" maxlength="1000" required placeholder="Describe which official report you checked, its full-time 90-minute score, and why this is the same fixture."></textarea>
<div class="alert">Do not use extra-time or penalty-shootout scores. Submitting a proposal does not change any result. The link is stored as evidence; BetSightly does not independently retrieve or verify the page.</div>
<div class="controls"><button class="primary" id="propose" type="submit" disabled>Propose evidence</button></div>
</form>
<section id="approval"><div class="sep"></div><h2>Confirm and approve</h2>
<p class="muted">Check the official URL independently and repeat the saved event ID to authorize settlement.</p>
<label for="confirm">Confirm exact SportyBet event ID</label><input id="confirm" placeholder="sr:match:…" autocomplete="off">
<label class="check"><input id="attest" type="checkbox"> <span>I independently checked this official source. These are the correct final 90-minute scores for this exact fixture and exclude extra time and penalties.</span></label>
<div class="controls"><button class="primary" id="approve" type="button">Approve verified score and settle</button><button id="cancel" type="button">Cancel approval</button></div>
</section>
<div id="status" class="notice" role="status" aria-live="polite"></div>
</section>
</div>
</main>
<script>
(() => {
  const base = location.pathname.replace(/\/desk\/?$/, '').replace(/\/$/, '');
  const $ = id => document.getElementById(id);
  let rows = [], selected = null, proposal = null, pending = false;
  const msg = (text, error=false) => { $('status').textContent = text; $('status').className = 'notice ' + (error?'error':'ok'); };
  const value = key => selected && selected[key] ? String(selected[key]) : '';
  const lock = busy => { pending = busy; $('propose').disabled = busy || !selected; $('approve').disabled = busy; };
  async function api(url, options={}) {
    const r = await fetch(url,{credentials:'same-origin',cache:'no-store',...options});
    let data;
    try { data=await r.json(); } catch { throw Error('Server returned an invalid response'); }
    if(!r.ok) throw Error(typeof data.detail==='string'?data.detail: 'Request failed ('+r.status+')');
    return data;
  }
  function choose(row) {
    selected = row; proposal = null; $('approval').style.display = 'none';
    $('selected').textContent = row.date+' · '+row.tier+' · '+row.home+' vs '+row.away+
       ' · '+row.event_id+' · '+(row.country||'Country unknown')+' · '+(row.league||'League unknown');
    $('hs').value=''; $('as').value=''; $('url').value=''; $('note').value='';
    $('confirm').value=''; $('attest').checked=false;
    lock(false); render(); msg('Select the official report and verify the 90-minute score before proposing.');
  }
  function render() {
    const needle = $('filter').value.trim().toLowerCase();
    const host=$('events'); host.replaceChildren();
    const filtered=rows.filter(r => [r.home,r.away,r.league,r.country,r.event_id,r.date].some(v=>String(v||'').toLowerCase().includes(needle)));
    $('shown').textContent=filtered.length+' displayed';
    for(const row of filtered.slice(0,250)) {
      const btn=document.createElement('button');
      btn.type='button'; btn.className='event'+(selected&&row.event_id===selected.event_id?' sel':'');
      const b=document.createElement('b'); b.textContent=(row.home||'Unknown')+' vs '+(row.away||'Unknown');
      const m=document.createElement('small'); m.textContent=[row.date,row.tier,row.country||'country unknown',row.league||'',row.event_id].join(' · ');
      btn.append(b,m); btn.onclick=()=>choose(row); host.append(btn);
    }
    if(!filtered.length){const p=document.createElement('p'); p.className='muted';p.textContent='No records match this filter.';host.append(p);}
  }
  async function load() {
    lock(true); msg('Loading saved pending fixtures…');
    try {
      const data=await api(base+'?limit=1000');
      rows=data.legs||[]; $('pending').textContent=data.total_pending_legs;
      $('overdue').textContent=data.overdue_48h; $('unique').textContent=data.unique_events;
      if(selected&&!rows.some(r=>r.event_id===selected.event_id&&r.tier===selected.tier)) {
        selected=null; proposal=null; $('approval').style.display='none';
        $('selected').textContent='Select an unresolved match on the left.';
      }
      render(); msg('Latest saved manual records loaded. '+data.returned+' shown from '+data.total_pending_legs+' pending legs.');
    } catch(e){msg(e.message,true);}
    finally{lock(false);}
  }
  $('refresh').onclick=load; $('filter').oninput=render;
  $('proposal').onsubmit=async e=>{
    e.preventDefault();if(!selected||pending)return;
    lock(true);msg('Checking exact saved fixture and recording evidence proposal…');
    const body={
      publish_date:selected.date,tier:selected.tier,event_id:selected.event_id,
      home_score:Number($('hs').value),away_score:Number($('as').value),
      evidence_url:$('url').value,evidence_note:$('note').value
    };
    try {
      proposal=await api(base+'/propose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      $('approval').style.display='block';
      msg('Proposal '+proposal.review_id+' saved; no results changed. Independently check the evidence before approval.');
    }catch(e){msg(e.message,true);}
    finally{lock(false);}
  };
  $('approve').onclick=async()=>{
    if(!selected||!proposal||pending)return;
    lock(true);msg('Applying exact-event verified score to pending ticket legs…');
    try {
      const result=await api(base+'/approve',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({review_id:proposal.review_id,confirmed_event_id:$('confirm').value,
          attest_regulation_90:$('attest').checked})});
      msg('Saved: '+result.legs_updated+' exact-event legs settled. Booking codes unchanged.');
      proposal=null;$('approval').style.display='none';await load();
    }catch(e){msg(e.message,true);}
    finally{lock(false);}
  };
  $('cancel').onclick=()=>{proposal=null;$('approval').style.display='none';msg('Approval canceled. Pending tickets unchanged.');};
  load();
})();
</script>
</body></html>'''


def access_page() -> str:
    """Login hand-off: password stays inside the existing Render auth service."""
    return r'''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>BetSightly · Protected Evidence Desk</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{background:radial-gradient(circle at 90% 10%,#164961,#071825 65%);min-height:100vh;display:grid;place-items:center;margin:0;color:#ecf5fa;font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}
main{background:#102d43;border:1px solid #386078;box-shadow:0 20px 60px #03111b90;border-radius:17px;padding:32px;max-width:430px;width:calc(100% - 30px)}
.tag{font-size:12px;letter-spacing:2px;color:#81cbe2;font-weight:800}
h1{line-height:1.16;letter-spacing:-.6px;font-size:28px;margin:10px 0 8px}
p{color:#bad0dc}label{display:block;margin:20px 0 7px;font-weight:700}
input{background:#092238;border:1px solid #5687a0;border-radius:9px;color:white;font:inherit;padding:13px;width:100%}
button{background:#2380a7;border:1px solid #3299c1;border-radius:9px;padding:13px 16px;color:#fff;font-weight:800;font:inherit;cursor:pointer;width:100%;margin-top:15px}
button:disabled{opacity:.55;cursor:wait}#msg{min-height:24px;color:#f2a9a9;margin-top:14px;font-size:13px}
small{color:#98b8cb}
</style></head><body><main>
<div class="tag">BET SIGHTLY / PROTECTED OPERATIONS</div>
<h1>Settlement Evidence Desk</h1>
<p>Sign in using the existing BetSightly administrator password. The password is submitted directly to the protected Render backend; it is not stored or shown in this page.</p>
<form id="f">
<label for="password">Administrator password</label>
<input id="password" type="password" autocomplete="current-password" required autofocus>
<button type="submit" id="submit">Secure sign in</button>
</form><div id="msg" role="alert" aria-live="polite"></div>
<small>Signed session · HttpOnly · Secure · SameSite=Strict</small>
</main><script>
document.getElementById('f').addEventListener('submit',async event=>{
  event.preventDefault();
  const button=document.getElementById('submit'),status=document.getElementById('msg');
  const password=document.getElementById('password').value;
  button.disabled=true;status.textContent='Verifying administrator session…';
  try{
    const result=await fetch('/api/growth/admin/login',{
      method:'POST',credentials:'same-origin',cache:'no-store',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({password})});
    if(!result.ok){
      let error={};try{error=await result.json()}catch{}
      throw Error(typeof error.detail==='string'?error.detail:'Administrator login failed');
    }
    document.getElementById('password').value='';
    location.assign('/api/growth/manual-tiers/settlement-review/desk');
  }catch(error){status.textContent=error.message||'Sign-in failed';button.disabled=false;}
});
</script></body></html>'''
