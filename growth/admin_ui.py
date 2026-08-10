"""
The admin dashboard, served by the backend itself.

Served from FastAPI rather than added to the Vercel frontend on purpose. The
session is an httpOnly cookie, and if the dashboard lived on betsightly.com
while the API lives on betsightly-api.onrender.com, that cookie would be
third-party: Safari blocks those outright under ITP and Chrome is removing
them. The dashboard would appear to log in and then immediately act logged
out, intermittently and per-browser, which is a miserable thing to debug.

Serving both from one origin makes the cookie first-party and the problem
disappears. It also keeps an internal tool off the public site entirely, needs
no frontend deploy to change, and cannot leak into the public bundle.

Single self-contained document — no build step, no CDN, no external requests,
so it works under a strict CSP and cannot break because a third party did.
"""

ADMIN_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Growth · BetSightly Admin</title>
<style>
:root{
  --bg:#0b0f14; --panel:#11171f; --panel2:#161d27; --line:#1f2630;
  --text:#e6edf3; --dim:#8b949e; --brand:#2ea043; --warn:#d29922;
  --bad:#f85149; --info:#58a6ff;
  --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.5}
a{color:var(--info)}
header{display:flex;align-items:center;justify-content:space-between;gap:1rem;
  padding:1rem 1.25rem;border-bottom:1px solid var(--line);position:sticky;top:0;
  background:var(--bg);z-index:5;flex-wrap:wrap}
h1{font-size:1.05rem;margin:0;letter-spacing:.02em}
h2{font-size:.95rem;margin:0 0 .75rem;color:var(--dim);font-weight:600;
  text-transform:uppercase;letter-spacing:.06em}
main{max-width:1180px;margin:0 auto;padding:1.25rem}
.grid{display:grid;gap:1rem}
.cards{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.two{grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:1rem}
.stat{font-family:var(--mono);font-size:1.6rem;font-weight:700}
.stat small{display:block;font-family:inherit;font-size:.72rem;color:var(--dim);
  font-weight:500;text-transform:uppercase;letter-spacing:.05em;margin-top:.2rem}
.delta{font-size:.75rem;font-family:var(--mono)}
.up{color:var(--brand)} .down{color:var(--bad)}
button{background:var(--panel2);color:var(--text);border:1px solid var(--line);
  border-radius:7px;padding:.45rem .8rem;font-size:.82rem;cursor:pointer;font-family:inherit}
button:hover{border-color:var(--brand)}
button.primary{background:var(--brand);border-color:var(--brand);color:#fff;font-weight:600}
button.ghost{background:transparent}
button:disabled{opacity:.4;cursor:not-allowed}
input,select{background:var(--panel2);border:1px solid var(--line);color:var(--text);
  border-radius:7px;padding:.5rem .7rem;font-family:inherit;font-size:.85rem;width:100%}
table{width:100%;border-collapse:collapse;font-size:.83rem}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line);
  vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:.72rem;text-transform:uppercase;
  letter-spacing:.05em}
.tag{display:inline-block;padding:.12rem .5rem;border-radius:99px;font-size:.68rem;
  font-family:var(--mono);border:1px solid var(--line)}
.DRAFT{color:var(--warn);border-color:var(--warn)}
.APPROVED{color:var(--info);border-color:var(--info)}
.PUBLISHED{color:var(--brand);border-color:var(--brand)}
.FAILED{color:var(--bad);border-color:var(--bad)}
.CANCELLED{color:var(--dim)}
.SCHEDULED{color:var(--info);border-color:var(--info)}
.bar{height:6px;border-radius:3px;background:var(--brand);min-width:2px}
.row{display:flex;align-items:center;gap:.6rem}
.muted{color:var(--dim);font-size:.8rem}
pre{white-space:pre-wrap;word-break:break-word;background:var(--panel2);
  border:1px solid var(--line);border-radius:8px;padding:.75rem;font-size:.78rem;
  max-height:340px;overflow:auto;margin:0}
.tabs{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:1rem}
.tabs button.active{background:var(--brand);border-color:var(--brand);color:#fff}
.hidden{display:none}
#login{max-width:340px;margin:12vh auto;text-align:center}
.err{color:var(--bad);font-size:.82rem;min-height:1.2em}
.note{background:rgba(210,153,34,.09);border-left:3px solid var(--warn);
  padding:.6rem .8rem;border-radius:6px;font-size:.8rem;color:var(--dim);margin-bottom:1rem}
.switch{display:flex;align-items:center;justify-content:space-between;gap:1rem;
  padding:.45rem 0;border-bottom:1px solid var(--line);font-size:.85rem}
.switch:last-child{border-bottom:0}
</style>
</head>
<body>

<div id="login">
  <h1 style="margin-bottom:1rem">BetSightly Growth</h1>
  <div class="card">
    <p class="muted" style="margin-top:0">Admin sign-in</p>
    <input id="pw" type="password" placeholder="Password" autocomplete="current-password">
    <p class="err" id="loginErr"></p>
    <button class="primary" style="width:100%" onclick="doLogin()">Sign in</button>
  </div>
  <p class="muted" id="cfgNote" style="margin-top:1rem"></p>
</div>

<div id="app" class="hidden">
<header>
  <h1>Growth Engine <span class="muted" id="today"></span></h1>
  <div class="row">
    <button onclick="generate(false)">Generate</button>
    <button onclick="generate(true)">Generate + publish</button>
    <button onclick="retry()">Retry failed</button>
    <button class="ghost" onclick="doLogout()">Sign out</button>
  </div>
</header>

<main>
  <div class="tabs">
    <button class="active" onclick="tab('overview',this)">Overview</button>
    <button onclick="tab('content',this)">Content</button>
    <button onclick="tab('publications',this)">Publishing</button>
    <button onclick="tab('settings',this)">Settings</button>
    <button onclick="tab('referrals',this)">Referrals</button>
  </div>

  <section id="tab-overview">
    <div class="row" style="margin-bottom:1rem">
      <label class="muted">Window</label>
      <select id="win" style="width:auto" onchange="loadAnalytics()">
        <option value="1">Today</option><option value="7" selected>7 days</option>
        <option value="30">30 days</option><option value="90">90 days</option>
      </select>
    </div>
    <div class="grid cards" id="stats"></div>
    <div class="grid two" style="margin-top:1rem">
      <div class="card"><h2>Acquisition</h2><div id="bySource"></div></div>
      <div class="card"><h2>Campaigns</h2><div id="byCampaign"></div></div>
      <div class="card"><h2>Top pages</h2><div id="byPath"></div></div>
      <div class="card"><h2>Creators</h2><div id="byRef"></div></div>
    </div>
  </section>

  <section id="tab-content" class="hidden">
    <div class="note">
      Instagram, Facebook, TikTok and YouTube are generated for manual posting.
      Automated betting posts on those platforms can get the account terminated,
      so there is no publish button — copy the text and post it yourself.
    </div>
    <div class="row" style="margin-bottom:.8rem">
      <select id="fPlatform" style="width:auto" onchange="loadContent()">
        <option value="">All platforms</option>
      </select>
      <select id="fStatus" style="width:auto" onchange="loadContent()">
        <option value="">All statuses</option>
        <option>DRAFT</option><option>APPROVED</option>
        <option>PUBLISHED</option><option>FAILED</option><option>CANCELLED</option>
      </select>
    </div>
    <div class="card" style="padding:0;overflow:auto"><table id="contentTable"></table></div>
    <div id="preview" class="card hidden" style="margin-top:1rem">
      <h2>Preview</h2><pre id="previewBody"></pre>
    </div>
  </section>

  <section id="tab-publications" class="hidden">
    <div class="card" style="padding:0;overflow:auto"><table id="pubTable"></table></div>
  </section>

  <section id="tab-settings" class="hidden">
    <div class="grid two">
      <div class="card"><h2>Engine</h2><div id="engineToggle"></div></div>
      <div class="card"><h2>Channels</h2><div id="channelToggles"></div></div>
      <div class="card"><h2>Auto-publish</h2>
        <p class="muted" style="margin-top:0">Off means content waits for approval.</p>
        <div id="autoToggles"></div></div>
      <div class="card"><h2>Schedule (UTC)</h2><div id="scheduleFields"></div></div>
    </div>
    <button class="primary" style="margin-top:1rem" onclick="saveSettings()">Save settings</button>
    <span class="muted" id="settingsMsg" style="margin-left:.6rem"></span>
  </section>

  <section id="tab-referrals" class="hidden">
    <div class="card">
      <h2>New referral code</h2>
      <div class="row">
        <input id="refCode" placeholder="code (e.g. bigmike)">
        <input id="refName" placeholder="name (optional)">
        <button class="primary" onclick="addRef()">Create</button>
      </div>
      <p class="err" id="refErr"></p>
    </div>
    <div class="card" style="margin-top:1rem;padding:0;overflow:auto">
      <table id="refTable"></table>
    </div>
  </section>
</main>
</div>

<script>
const API = '/api/growth';
const $ = id => document.getElementById(id);
let SETTINGS = {};

async function api(path, opts = {}) {
  const r = await fetch(API + path, {credentials:'same-origin',
    headers:{'Content-Type':'application/json'}, ...opts});
  if (r.status === 401) { show('login'); throw new Error('unauthorised'); }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || body.message || ('HTTP ' + r.status));
  return body;
}
function show(which){
  $('login').classList.toggle('hidden', which !== 'login');
  $('app').classList.toggle('hidden', which === 'login');
}
function tab(name, btn){
  ['overview','content','publications','settings','referrals']
    .forEach(t => $('tab-' + t).classList.toggle('hidden', t !== name));
  document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  if (name === 'content') loadContent();
  if (name === 'publications') loadPubs();
  if (name === 'settings') loadSettings();
  if (name === 'referrals') loadRefs();
}
const esc = s => String(s == null ? '' : s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

async function doLogin(){
  $('loginErr').textContent = '';
  try {
    await api('/admin/login', {method:'POST',
      body: JSON.stringify({password: $('pw').value})});
    $('pw').value = '';
    show('app'); boot();
  } catch(e) { $('loginErr').textContent = e.message; }
}
async function doLogout(){
  try { await api('/admin/logout', {method:'POST'}); } catch(e){}
  show('login');
}

async function boot(){
  $('today').textContent = new Date().toISOString().slice(0,10);
  loadAnalytics(); loadStatus();
}

async function loadAnalytics(){
  const days = $('win').value;
  let d;
  try { d = await api('/analytics?days=' + days); } catch(e){ return; }
  const t = d.summary.totals, v = d.vs_previous;
  const pct = x => x == null ? '—' : (x*100).toFixed(1) + '%';
  let delta = '';
  if (v && v.change != null) {
    const cls = v.change >= 0 ? 'up' : 'down';
    delta = `<span class="delta ${cls}">${v.change>=0?'▲':'▼'} ${Math.abs(v.change*100).toFixed(0)}%</span>`;
  }
  $('stats').innerHTML = [
    ['Visitors', t.visitors, delta], ['New', t.new_visitors, ''],
    ['Returning', t.returning_visitors, ''], ['Pageviews', t.pageviews, ''],
    ['Telegram clicks', t.telegram_clicks, ''],
    ['Conversion', pct(t.conversion_rate), ''],
  ].map(([label, val, d]) =>
    `<div class="card"><div class="stat">${esc(val)} ${d}<small>${esc(label)}</small></div></div>`
  ).join('');

  const bars = (rows, el) => {
    const max = Math.max(1, ...rows.map(r => r.count));
    $(el).innerHTML = rows.length ? rows.slice(0,8).map(r =>
      `<div style="margin-bottom:.55rem">
         <div class="row" style="justify-content:space-between">
           <span style="font-size:.82rem">${esc(r.key)}</span>
           <span class="muted" style="font-family:var(--mono)">${r.count}</span></div>
         <div class="bar" style="width:${(r.count/max*100).toFixed(1)}%"></div></div>`
    ).join('') : '<p class="muted">No data yet.</p>';
  };
  bars(d.summary.by_source, 'bySource');
  bars(d.summary.by_campaign, 'byCampaign');
  bars(d.summary.by_path, 'byPath');
  bars(d.summary.by_ref, 'byRef');
}

async function loadStatus(){
  let s; try { s = await api('/status'); } catch(e){ return; }
  SETTINGS = s.settings || {};
  const sel = $('fPlatform');
  if (sel.options.length <= 1) {
    Object.keys(SETTINGS.channel_enabled || {}).forEach(ch => {
      const o = document.createElement('option'); o.value = o.textContent = ch;
      sel.appendChild(o);
    });
  }
}

async function loadContent(){
  const p = $('fPlatform').value, st = $('fStatus').value;
  let d; try {
    d = await api('/content?limit=400' + (p?'&platform='+p:'') + (st?'&status='+st:''));
  } catch(e){ return; }
  const draftOnly = ['instagram','facebook','tiktok','youtube','x'];
  $('contentTable').innerHTML =
    '<tr><th>Template</th><th>Platform</th><th>Status</th><th>Date</th><th></th></tr>' +
    (d.content.length ? d.content.map(c => `
      <tr>
        <td>${esc(c.template)}</td>
        <td>${esc(c.platform)}</td>
        <td><span class="tag ${esc(c.status)}">${esc(c.status)}</span>
            ${c.error ? `<div class="muted">${esc(c.error.slice(0,60))}</div>` : ''}</td>
        <td class="muted">${esc(c.publish_date)}</td>
        <td class="row">
          <button onclick="preview(${c.id})">View</button>
          ${c.status === 'DRAFT' ? `<button onclick="act(${c.id},'approve')">Approve</button>` : ''}
          ${(!draftOnly.includes(c.platform) && c.status !== 'PUBLISHED')
            ? `<button class="primary" onclick="act(${c.id},'publish')">Publish</button>` : ''}
          ${c.status !== 'PUBLISHED' && c.status !== 'CANCELLED'
            ? `<button onclick="act(${c.id},'cancel')">Cancel</button>` : ''}
        </td>
      </tr>`).join('')
      : '<tr><td colspan="5" class="muted" style="padding:1rem">Nothing generated yet.</td></tr>');
}

async function preview(id){
  const d = await api('/content?limit=400');
  const c = d.content.find(x => x.id === id);
  if (!c) return;
  const p = c.payload || {};
  let body = p.text || p.caption || '';
  if (!body && p.script) body = 'HOOK: ' + (p.hook||'') + '\n\n' + p.script.join('\n') + '\n\nCTA: ' + (p.cta||'');
  if (!body) body = JSON.stringify(p, null, 2);
  $('previewBody').textContent = body;
  $('preview').classList.remove('hidden');
  $('preview').scrollIntoView({behavior:'smooth'});
}

async function act(id, what){
  try { await api(`/content/${id}/${what}`, {method:'POST'}); loadContent(); }
  catch(e){ alert(e.message); }
}
async function generate(publish){
  try {
    const d = await api('/generate?publish=' + (publish?'true':'false'), {method:'POST'});
    const r = d.report;
    alert(`Generated ${r.generated}, stored ${r.stored}, already had ${r.skipped}.\n` +
          `Published ${r.published.length}, failed ${r.failed.length}.` +
          (r.notes.length ? '\n' + r.notes.join('\n') : ''));
    loadContent();
  } catch(e){ alert(e.message); }
}
async function retry(){
  try { const d = await api('/retry', {method:'POST'});
    alert(`Retried ${d.attempted}, recovered ${d.recovered}.`); loadPubs(); }
  catch(e){ alert(e.message); }
}

async function loadPubs(){
  let d; try { d = await api('/publications?limit=300'); } catch(e){ return; }
  $('pubTable').innerHTML =
    '<tr><th>Date</th><th>Channel</th><th>Template</th><th>Status</th><th>Tries</th><th>Detail</th></tr>' +
    (d.publications.length ? d.publications.map(p => `
      <tr><td class="muted">${esc(p.publish_date)}</td><td>${esc(p.channel)}</td>
      <td>${esc(p.template)}</td>
      <td><span class="tag ${esc(p.status)}">${esc(p.status)}</span></td>
      <td class="muted">${p.attempts}</td>
      <td class="muted">${esc(p.last_error ? p.last_error.slice(0,70) : (p.external_id||''))}</td></tr>`
    ).join('') : '<tr><td colspan="6" class="muted" style="padding:1rem">Nothing published yet.</td></tr>');
}

async function loadSettings(){
  let d; try { d = await api('/settings'); } catch(e){ return; }
  SETTINGS = d.settings;
  $('engineToggle').innerHTML =
    `<div class="switch"><span>Growth Engine enabled</span>
     <input type="checkbox" id="s_engine" style="width:auto" ${SETTINGS.engine_enabled?'checked':''}></div>`;
  const toggles = (obj, prefix, el) => {
    $(el).innerHTML = Object.entries(obj || {}).map(([k,v]) =>
      `<div class="switch"><span>${esc(k)}</span>
       <input type="checkbox" style="width:auto" id="${prefix}_${esc(k)}" ${v?'checked':''}></div>`
    ).join('');
  };
  toggles(SETTINGS.channel_enabled, 'ch', 'channelToggles');
  toggles(SETTINGS.channel_auto_publish, 'auto', 'autoToggles');
  $('scheduleFields').innerHTML = Object.entries(SETTINGS.schedule || {}).map(([k,v]) =>
    `<div class="switch"><span>${esc(k)}</span>
     <input id="sch_${esc(k)}" value="${esc(v)}" style="width:90px" placeholder="HH:MM"></div>`
  ).join('');
}
async function saveSettings(){
  const ch = {}, auto = {}, sch = {};
  Object.keys(SETTINGS.channel_enabled||{}).forEach(k => ch[k] = $('ch_'+k).checked);
  Object.keys(SETTINGS.channel_auto_publish||{}).forEach(k => auto[k] = $('auto_'+k).checked);
  Object.keys(SETTINGS.schedule||{}).forEach(k => sch[k] = $('sch_'+k).value.trim());
  try {
    await api('/settings', {method:'POST', body: JSON.stringify({
      engine_enabled: $('s_engine').checked,
      channel_enabled: ch, channel_auto_publish: auto, schedule: sch})});
    $('settingsMsg').textContent = 'Saved.';
    setTimeout(() => $('settingsMsg').textContent = '', 2500);
  } catch(e){ $('settingsMsg').textContent = e.message; }
}

async function loadRefs(){
  let d; try { d = await api('/referrals'); } catch(e){ return; }
  $('refTable').innerHTML =
    '<tr><th>Code</th><th>Name</th><th>Link</th></tr>' +
    (d.referrals.length ? d.referrals.map(r => {
      const link = `https://www.betsightly.com/predictions?utm_source=referral&utm_medium=referral&utm_campaign=creator&ref=${encodeURIComponent(r.code)}`;
      return `<tr><td><code>${esc(r.code)}</code></td><td>${esc(r.name||'')}</td>
        <td class="muted" style="word-break:break-all">${esc(link)}</td></tr>`;
    }).join('') : '<tr><td colspan="3" class="muted" style="padding:1rem">No referral codes yet.</td></tr>');
}
async function addRef(){
  $('refErr').textContent = '';
  try {
    await api('/referrals', {method:'POST', body: JSON.stringify({
      code: $('refCode').value, name: $('refName').value})});
    $('refCode').value = $('refName').value = ''; loadRefs();
  } catch(e){ $('refErr').textContent = e.message; }
}

$('pw').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

(async () => {
  try {
    const cfg = await (await fetch(API + '/admin/config')).json();
    if (!cfg.configured) {
      $('cfgNote').textContent =
        'Admin login is not configured. Set ADMIN_PASSWORD_HASH and SECRET_KEY on the server.';
    }
  } catch(e){}
  try { await api('/admin/me'); show('app'); boot(); }
  catch(e){ show('login'); }
})();
</script>
</body>
</html>
"""
