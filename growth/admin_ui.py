"""Protected, same-origin BetSightly command center (no external runtime)."""

ADMIN_CSS = r"""
:root{
  color-scheme:dark;--bg:#07100e;--shell:#0a1512;--panel:#0e1c18;
  --panel-2:#12231e;--panel-3:#172b25;--line:#20372f;--line-2:#2b493e;
  --text:#f4f8f6;--text-2:#b6c7c0;--muted:#789087;--brand:#24d17e;
  --brand-2:#11a962;--brand-soft:rgba(36,209,126,.11);--blue:#61a8ff;
  --amber:#f3b95f;--red:#ff6b70;--purple:#ac8cff;--radius:16px;
  --shadow:0 20px 60px rgba(0,0,0,.22);--mono:"SFMono-Regular",Consolas,monospace;
}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:radial-gradient(circle at 70% -20%,rgba(36,209,126,.12),transparent 38%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.45}
button,input,select{font:inherit}button{cursor:pointer}.hidden{display:none!important}
.login-shell{min-height:100vh;display:grid;place-items:center;padding:24px}
.login-card{width:min(420px,100%);padding:32px;background:linear-gradient(145deg,var(--panel-2),var(--panel));border:1px solid var(--line-2);border-radius:24px;box-shadow:var(--shadow)}
.brand{display:flex;align-items:center;gap:12px;font-weight:800;letter-spacing:-.03em;font-size:18px}.brand-mark{width:36px;height:36px;display:grid;place-items:center;border-radius:11px;background:linear-gradient(145deg,var(--brand),#7df4b6);color:#052014;font-size:20px;box-shadow:0 8px 24px rgba(36,209,126,.22)}
.login-card h1{font-size:30px;margin:30px 0 8px;letter-spacing:-.045em}.login-card p{color:var(--text-2)}
.field{width:100%;background:var(--panel-3);border:1px solid var(--line);color:var(--text);border-radius:12px;padding:12px 14px;outline:none}.field:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}
.btn{border:1px solid var(--line-2);background:var(--panel-2);color:var(--text);border-radius:11px;min-height:40px;padding:9px 14px;font-weight:650}.btn:hover{border-color:#47705f;background:var(--panel-3)}.btn-primary{background:linear-gradient(135deg,var(--brand),var(--brand-2));border:0;color:#032116}.btn-ghost{background:transparent}.btn-danger{color:var(--red)}.btn:disabled{opacity:.45;cursor:not-allowed}.btn-wide{width:100%;margin-top:12px}
.error{color:var(--red);font-size:13px;min-height:20px}.muted{color:var(--muted)}
.shell{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh}
.sidebar{position:sticky;top:0;height:100vh;border-right:1px solid var(--line);background:rgba(7,16,14,.88);backdrop-filter:blur(20px);padding:24px 16px;display:flex;flex-direction:column;z-index:10}
.sidebar .brand{padding:0 8px 24px}.nav-label{font-size:10px;text-transform:uppercase;letter-spacing:.16em;color:var(--muted);font-weight:750;padding:14px 12px 7px}.nav{display:grid;gap:3px}.nav button{width:100%;border:0;background:transparent;color:var(--text-2);text-align:left;padding:10px 12px;border-radius:10px;font-weight:600;display:flex;align-items:center;gap:10px}.nav button:hover{color:var(--text);background:var(--panel)}.nav button.active{color:var(--text);background:var(--brand-soft);box-shadow:inset 3px 0 var(--brand)}.nav-icon{width:20px;text-align:center;color:var(--muted)}.nav button.active .nav-icon{color:var(--brand)}
.sidebar-foot{margin-top:auto;border-top:1px solid var(--line);padding-top:16px}.live{display:flex;align-items:center;gap:8px;color:var(--text-2);font-size:12px;padding:8px}.dot{width:7px;height:7px;border-radius:50%;background:var(--brand);box-shadow:0 0 0 5px var(--brand-soft)}
.workspace{min-width:0}.topbar{height:76px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 30px;border-bottom:1px solid var(--line);background:rgba(7,16,14,.72);backdrop-filter:blur(18px);position:sticky;top:0;z-index:9}.topbar-title strong{display:block;font-size:15px}.topbar-title span{font-size:12px;color:var(--muted)}.actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
main{max-width:1520px;margin:0 auto;padding:28px 30px 64px}.page{display:none}.page.active{display:block}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:24px}.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.16em;color:var(--brand);font-weight:800;margin:0 0 7px}.page-head h1{font-size:30px;line-height:1.05;letter-spacing:-.045em;margin:0}.page-head p{color:var(--text-2);margin:8px 0 0;font-size:14px}.range{display:flex;align-items:center;gap:5px;min-width:0;max-width:100%;padding:5px;background:var(--panel);border:1px solid var(--line);border-radius:12px}.range button{border:0;background:transparent;color:var(--muted);border-radius:8px;padding:7px 11px;font-size:12px;font-weight:700}.range button.active{background:var(--panel-3);color:var(--text);box-shadow:0 1px 8px rgba(0,0,0,.2)}
.grid{display:grid;gap:14px}.kpis{grid-template-columns:repeat(6,minmax(130px,1fr))}.two{grid-template-columns:repeat(2,minmax(0,1fr))}.three{grid-template-columns:repeat(3,minmax(0,1fr))}.span-2{grid-column:span 2}.section{margin-top:24px}.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.section-head h2{font-size:15px;margin:0;letter-spacing:-.015em}.section-head p{font-size:12px;color:var(--muted);margin:0}
.card{background:linear-gradient(145deg,rgba(18,35,30,.96),rgba(12,26,22,.96));border:1px solid var(--line);border-radius:var(--radius);padding:18px;box-shadow:0 1px 0 rgba(255,255,255,.02)}.card:hover{border-color:#2b493e}.card-flush{padding:0;overflow:hidden}.card-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}.card-title h3{font-size:13px;margin:0;color:var(--text-2)}
.card-flush>.card-title{padding:18px 18px 0}
.kpi{min-height:126px;position:relative;overflow:hidden}.kpi:after{content:"";position:absolute;width:80px;height:80px;border-radius:50%;right:-32px;top:-36px;background:var(--brand-soft)}.kpi-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;font-weight:750}.kpi-value{font:750 28px/1.1 var(--mono);letter-spacing:-.055em;margin:14px 0 8px}.delta{font:650 11px var(--mono);color:var(--muted)}.delta.up{color:var(--brand)}.delta.down{color:var(--red)}.kpi.hero{border-color:rgba(36,209,126,.4);background:linear-gradient(145deg,rgba(36,209,126,.16),var(--panel))}.kpi.hero .kpi-value{color:#75f0b1}
.health-grid{display:grid;grid-template-columns:1.2fr repeat(3,1fr);gap:0}.health-item{padding:16px;border-left:1px solid var(--line)}.health-item:first-child{border-left:0}.health-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}.health-value{font-size:18px;font-weight:750;margin-top:7px}.status{display:inline-flex;align-items:center;gap:6px;border-radius:99px;padding:4px 8px;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.06em}.ok{background:rgba(36,209,126,.12);color:var(--brand)}.warning{background:rgba(243,185,95,.12);color:var(--amber)}.bad{background:rgba(255,107,112,.12);color:var(--red)}.neutral{background:rgba(120,144,135,.13);color:var(--text-2)}
.funnel{display:grid;gap:7px}.funnel-row{display:grid;grid-template-columns:1fr auto 90px;gap:14px;align-items:center;padding:10px 12px;border-radius:10px;background:rgba(255,255,255,.018)}.funnel-row.worst{background:rgba(255,107,112,.07);outline:1px solid rgba(255,107,112,.18)}.funnel-name{font-size:13px;font-weight:650}.funnel-count{font:700 13px var(--mono)}.funnel-rate{text-align:right;font:600 11px var(--mono);color:var(--muted)}
.trend{height:170px;display:flex;align-items:flex-end;gap:5px;padding-top:14px}.trend-col{flex:1;min-width:5px;display:flex;flex-direction:column;justify-content:flex-end;height:100%;gap:5px}.trend-bar{width:100%;min-height:3px;border-radius:5px 5px 2px 2px;background:linear-gradient(180deg,var(--brand),rgba(36,209,126,.2))}.trend-col span{font:9px var(--mono);color:var(--muted);text-align:center;white-space:nowrap;overflow:hidden}.legend{display:flex;gap:16px;font-size:11px;color:var(--muted)}
.metric-list{display:grid;gap:11px}.metric-row{display:grid;grid-template-columns:minmax(100px,1fr) auto;gap:12px;align-items:center}.metric-row strong{font-size:12px}.metric-row span{font:650 12px var(--mono)}.mini-track{grid-column:1/-1;height:5px;background:rgba(255,255,255,.04);border-radius:4px;overflow:hidden}.mini-fill{height:100%;background:var(--brand);border-radius:4px}
.retention{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.retention-cell{padding:15px 10px;border-radius:12px;background:rgba(255,255,255,.025);text-align:center}.retention-cell strong{display:block;font:750 18px var(--mono)}.retention-cell span{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.alert{display:flex;gap:12px;padding:13px 0;border-bottom:1px solid var(--line)}.alert:last-child{border-bottom:0}.alert-icon{width:28px;height:28px;border-radius:8px;display:grid;place-items:center;background:rgba(243,185,95,.12);color:var(--amber);flex:0 0 auto}.alert strong{display:block;font-size:12px}.alert p{font-size:11px;color:var(--muted);margin:3px 0 0}
.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:620px}th,td{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;font-size:12px}th{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:750;background:rgba(255,255,255,.012)}td.num{font-family:var(--mono)}tr:last-child td{border-bottom:0}tbody tr:hover{background:rgba(255,255,255,.018)}
.empty{padding:28px;text-align:center;color:var(--muted);font-size:12px}.note{border:1px solid rgba(243,185,95,.22);background:rgba(243,185,95,.06);border-radius:12px;padding:12px 14px;color:var(--text-2);font-size:12px}.row{display:flex;align-items:center;gap:9px}.wrap{flex-wrap:wrap}.switch{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:11px 0;border-bottom:1px solid var(--line);font-size:12px}.switch:last-child{border-bottom:0}.switch input{accent-color:var(--brand)}
.tag{display:inline-flex;padding:3px 7px;border:1px solid var(--line-2);border-radius:99px;font:700 10px var(--mono)}.PUBLISHED,.FULL{color:var(--brand);border-color:rgba(36,209,126,.35)}.FAILED,.UNAVAILABLE{color:var(--red);border-color:rgba(255,107,112,.35)}.DRAFT{color:var(--amber)}.APPROVED,.SCHEDULED,.REBUILT_FULL{color:var(--blue)}.PARTIAL{color:var(--purple)}pre{white-space:pre-wrap;word-break:break-word;background:#08110f;border:1px solid var(--line);border-radius:12px;padding:15px;font:11px/1.6 var(--mono);max-height:420px;overflow:auto}
.mobile-toggle{display:none}
@media(max-width:1180px){.kpis{grid-template-columns:repeat(3,1fr)}.three{grid-template-columns:1fr 1fr}.health-grid{grid-template-columns:1fr 1fr}.health-item:nth-child(3){border-left:0;border-top:1px solid var(--line)}.health-item:nth-child(4){border-top:1px solid var(--line)}}
@media(max-width:800px){.shell{display:block}.sidebar{position:fixed;inset:0 auto 0 0;width:250px;transform:translateX(-105%);transition:.2s;box-shadow:var(--shadow)}.sidebar.open{transform:none}.mobile-toggle{display:inline-flex}.topbar{height:auto;min-height:66px;padding:12px 16px}.topbar .actions .desktop-action{display:none}main{padding:22px 16px 50px}.page-head{align-items:flex-start;flex-direction:column}.page-head>div{width:100%;min-width:0}.range{width:100%;overflow:auto}.kpis{grid-template-columns:1fr 1fr}.two,.three{grid-template-columns:1fr}.span-2{grid-column:auto}.health-grid{grid-template-columns:1fr}.health-item{border-left:0;border-top:1px solid var(--line)}.health-item:first-child{border-top:0}.retention{grid-template-columns:repeat(3,1fr)}}
@media(max-width:480px){.kpis{grid-template-columns:1fr 1fr}.kpi{min-height:112px;padding:14px}.kpi-value{font-size:23px}.funnel-row{grid-template-columns:1fr auto}.funnel-rate{grid-column:1/-1;text-align:left}.retention{grid-template-columns:1fr 1fr}.page-head h1{font-size:26px}}

/* Atlantic Blue / editorial admin system. Green and red remain semantic status colors. */
:root {
  --bg:#0B2238;--shell:#102A42;--panel:#1A354A;--panel-2:#203E55;
  --panel-3:#294961;--line:#35546D;--line-2:#4D6A80;
  --text:#F5F9FC;--text-2:#C4D5E2;--muted:#ABC0CF;
  --brand:#69B0D6;--brand-2:#4D9EC9;--brand-soft:rgba(105,176,214,.13);
  --blue:#91BAF1;--amber:#E5AD70;--red:#FF969C;--purple:#BAA9E8;
  --success:#77D4B6;--radius:13px;--shadow:0 16px 44px rgba(2,14,28,.22);
}
body { background:radial-gradient(circle at 70% -24%,rgba(105,176,214,.14),transparent 43%),var(--bg); }
.sidebar { background:rgba(11,34,56,.97); }
.topbar { background:rgba(11,34,56,.91); }
.card { background:linear-gradient(145deg,rgba(30,57,79,.98),rgba(20,44,65,.98)); }
.card:hover {border-color:var(--line-2)}
.btn {border-radius:9px}
.btn:hover {border-color:var(--brand)}
.btn-primary { background:linear-gradient(120deg,#E5AD70,#D5A069); color:#122238; border:1px solid #E5AD70; }
.btn-primary:hover { background:#F0BD89; border-color:#F0BD89; color:#122238; }
.btn:disabled { opacity:.58; cursor:not-allowed; }
.btn:focus-visible,.field:focus-visible,.nav button:focus-visible {
  outline:2px solid var(--brand);outline-offset:3px;
}
.brand-mark {background:linear-gradient(145deg,#69B0D6,#A2BFFA);color:#0B2238;box-shadow:0 7px 24px rgba(105,176,214,.18)}
.kpi.hero {border-color:var(--line-2);background:linear-gradient(145deg,var(--panel-3),var(--panel))}
.kpi.hero .kpi-value {color:var(--text)}
.trend-bar {background:linear-gradient(180deg,var(--brand),rgba(105,176,214,.2))}
.ok {color:var(--success);background:rgba(119,212,182,.12)}
.PUBLISHED,.FULL {color:var(--success);border-color:rgba(119,212,182,.4)}
.dot {background:var(--success);box-shadow:0 0 0 5px rgba(119,212,182,.12)}
pre {background:#10283E}
.field {border-radius:9px;min-width:0}
#page-manual .card {min-width:0}
#page-manual textarea.field {line-height:1.65}
#page-manual .row.wrap>input.field {flex:1 1 240px}
#page-manual [data-act^="manual-"] {min-height:44px}
#page-manual label.btn {cursor:pointer}
.manual-workflow {
 display:grid;gap:13px;padding:18px 20px;margin-top:20px;
 border:1px solid var(--border-brand,var(--line-2));border-radius:12px;
 background:linear-gradient(125deg,var(--panel-2),var(--panel));
 box-shadow:0 9px 25px rgba(2,14,28,.10);
}
.manual-workflow-head {display:flex;align-items:flex-start;gap:11px}
.manual-workflow-icon {flex:0 0 35px;display:grid;place-items:center;height:35px;border-radius:10px;background:var(--brand-soft);color:var(--brand);font-size:18px}
.manual-workflow-copy{min-width:0;flex:1}
.manual-workflow-title{display:block;font-size:14px;color:var(--text);font-weight:780}
.manual-workflow-detail{display:block;margin-top:4px;color:var(--text-2);font-size:12px;line-height:1.5;overflow-wrap:anywhere}
.manual-workflow-steps {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px;list-style:none;margin:0;padding:0}
.manual-workflow-steps li {display:flex;gap:7px;align-items:center;min-width:0;padding:9px 8px;border:1px solid var(--line);border-radius:8px;color:var(--muted);font-size:11px;font-weight:620;background:rgba(10,30,47,.4)}
.manual-workflow-steps li::before {content:"";width:7px;height:7px;flex:0 0 7px;border-radius:50%;background:var(--line-2)}
.manual-workflow-steps li[data-step-state="active"] {color:var(--text);border-color:var(--brand);background:var(--brand-soft)}
.manual-workflow-steps li[data-step-state="active"]::before {background:var(--brand)}
.manual-workflow-steps li[data-step-state="done"] {color:var(--text-2)}
.manual-workflow-steps li[data-step-state="done"]::before {background:var(--success)}
.manual-workflow[data-state="error"] {border-color:rgba(255,150,156,.5)}
.manual-workflow[data-state="success"] {border-color:rgba(119,212,182,.4)}
.manual-workflow[data-state="busy"] .manual-workflow-icon::before {
 content:"";display:block;width:18px;height:18px;border-radius:50%;
 border:2px solid rgba(105,176,214,.28);border-top-color:var(--brand);
 animation:admin-progress-spin .85s linear infinite;
}
.manual-workflow[data-state="busy"] .manual-workflow-icon {font-size:0}
@keyframes admin-progress-spin {to{transform:rotate(360deg)}}
.manual-workflow-help {display:flex;flex-wrap:wrap;align-items:center;gap:9px}
.manual-workflow-help .muted {font-size:11px}
.manual-result {border:1px solid rgba(119,212,182,.36);background:rgba(119,212,182,.075);border-radius:10px;padding:12px 14px;font-size:12px;color:var(--text-2);line-height:1.6;overflow-wrap:anywhere}
.manual-result strong,.manual-result code{color:var(--text)}
.manual-published-head {display:flex;justify-content:space-between;align-items:center;gap:12px}
.manual-published-head .btn {min-height:40px}
@media(max-width:850px) {
 .manual-workflow-steps {grid-template-columns:repeat(3,minmax(0,1fr))}
 .manual-workflow {padding:14px}
}
@media(max-width:520px) {
 .manual-workflow-steps {grid-template-columns:repeat(2,minmax(0,1fr))}
 .manual-workflow-head {gap:8px}
 #page-manual .row.wrap > :is(button,.btn) {flex:1 1 175px}
 #page-manual .row.wrap > label.btn {text-align:center}
 .manual-workflow-steps li {font-size:10px;min-height:40px}
}
@media(prefers-reduced-motion:reduce) {
 .manual-workflow[data-state="busy"] .manual-workflow-icon::before {animation-duration:2s}
}

.admin-inline-spinner{display:inline-block;vertical-align:middle;width:14px;height:14px;border:2px solid var(--line-2);border-top-color:var(--brand);border-radius:50%;animation:admin-progress-spin .8s linear infinite;margin-right:8px}
@media(prefers-reduced-motion:reduce){.admin-inline-spinner{animation-duration:2s}}
"""

ADMIN_JS = r"""
const API='/api/growth', $=id=>document.getElementById(id);let SETTINGS={},DASH=null;
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const pct=v=>v==null?'—':(Number(v)*100).toFixed(Number(v)<.1?1:0)+'%';
const num=v=>Number(v||0).toLocaleString();
const maybeNum=v=>v==null?'—':num(v);
const when=v=>{if(!v)return'Awaiting today’s run';const d=new Date(v);return Number.isNaN(d.valueOf())?String(v):d.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})};
async function api(path,opts={}){
 let r;
 try{r=await fetch(API+path,{credentials:'same-origin',headers:{'Content-Type':'application/json'},...opts})}
 catch(e){throw Error('Network request failed. Check your connection. Publication was not confirmed.')}
 if(r.status===401){show('login');throw Error('Session expired. Sign in again.')}
 const b=await r.json().catch(()=>({}));
 if(!r.ok){
  const detail=b.detail||b.message;
  const why=Array.isArray(detail)?detail.map(x=>x.msg||x.message||'Invalid input').join('; '):
   typeof detail==='string'?detail:detail?JSON.stringify(detail):'HTTP '+r.status;
  throw Error(why||'HTTP '+r.status);
 }
 return b;
}
function show(which){$('login').classList.toggle('hidden',which!=='login');$('app').classList.toggle('hidden',which==='login')}
function nav(name,button){document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-'+name));document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));if(button)button.classList.add('active');$('side').classList.remove('open');if(name==='content'){loadContent();loadHomeCampaign()}if(name==='publishing')loadPubs();if(name==='settings')loadSettings();if(name==='referrals')loadRefs();if(name==='manual'){syncManualTier();loadManual();manualUpdatePublishAvailability()}}
async function login(){try{await api('/admin/login',{method:'POST',body:JSON.stringify({password:$('pw').value})});$('pw').value='';show('app');boot()}catch(e){$('loginErr').textContent=e.message}}
async function logout(){try{await api('/admin/logout',{method:'POST'})}catch(e){}show('login')}
function delta(metric){const v=DASH?.vs_previous?.changes?.[metric];if(v==null)return'<span class="delta">No prior baseline</span>';return`<span class="delta ${v>=0?'up':'down'}">${v>=0?'↗':'↘'} ${Math.abs(v*100).toFixed(0)}% vs prior</span>`}
function kpi(label,value,metric,hero=false,format='num'){return`<article class="card kpi ${hero?'hero':''}"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${format==='pct'?pct(value):typeof value==='string'?esc(value):num(value)}</div>${delta(metric)}</article>`}
function sourceLine(meta){if(!meta)return'';const age=meta.freshness_seconds==null?'age unknown':meta.freshness_seconds<60?'just now':Math.round(meta.freshness_seconds/60)+'m old';return`<span class="status ${meta.status==='fresh'?'ok':meta.status==='stale'?'warning':'bad'}">${esc(meta.source)} · ${esc(meta.status)} · ${age}</span>`}
function empty(text='No data in this period yet.'){return`<div class="empty">${esc(text)}</div>`}
function table(headers,rows){return rows.length?`<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`:empty()}
function bars(rows,value='visitors'){if(!rows?.length)return empty();const max=Math.max(1,...rows.map(r=>r[value]||0));return`<div class="metric-list">${rows.slice(0,8).map(r=>`<div class="metric-row"><strong>${esc(r.key)}</strong><span>${num(r[value])}</span><div class="mini-track"><div class="mini-fill" style="width:${Math.max(2,(r[value]||0)/max*100)}%"></div></div></div>`).join('')}</div>`}
function renderTrend(rows){if(!rows?.length)return empty();const max=Math.max(1,...rows.map(r=>r.visitors));return`<div class="trend">${rows.map(r=>`<div class="trend-col" title="${esc(r.date)} · ${r.visitors} visitors"><div class="trend-bar" style="height:${Math.max(3,r.visitors/max*100)}%"></div><span>${esc(r.date.slice(5))}</span></div>`).join('')}</div>`}
function funnel(rows){if(!rows?.length)return empty();let worst=-1;rows.forEach((x,i)=>{if(i&&x.dropoff>worst)worst=x.dropoff});return rows.map((x,i)=>`<div class="funnel-row ${i&&x.dropoff===worst&&x.dropoff>.2?'worst':''}"><span class="funnel-name">${esc(x.label)}</span><span class="funnel-count">${num(x.count)}</span><span class="funnel-rate">${i?(x.conversion==null?'No eligible prior step':`${pct(x.conversion)} continue · ${pct(x.dropoff)} drop`):'Entry'}</span></div>`).join('')}
function renderOverview(){const s=DASH.summary,t=s.totals,b=s.booking,sb=s.sportybet||{},runs=s.operations?.runs||[],last=runs[0],country=s.by_country?.[0]?.key||'—',mobile=s.by_device?.find(x=>String(x.key).toLowerCase()==='mobile'),mobileShare=t.visitors?((mobile?.visitors||0)/t.visitors):null;$('audienceKpis').innerHTML=[kpi('Visitors',t.visitors,'visitors'),kpi('Returning users',t.returning_visitors,'returning_visitors',true),kpi('Sessions',t.sessions,'sessions'),kpi('Primary country',country,'country'),kpi('Mobile share',mobileShare,'mobile',false,'pct')].join('');$('engagementKpis').innerHTML=[kpi('Prediction users',t.prediction_viewers,'prediction_viewers'),kpi('Builder users',t.builder_users,'builder_users'),kpi('Rollover users',t.rollover_users,'rollover_users'),kpi('Valid-code viewers',t.valid_code_viewers,'valid_code_viewers'),kpi('Unique code copiers',t.unique_code_copiers,'unique_code_copiers',true),kpi('SportyBet openers',t.sportybet_openers,'sportybet_openers')].join('');$('systemKpis').innerHTML=[kpi('Automated bookings',b.attempts,'attempts'),kpi('Successful bookings',(b.full||0)+(b.rebuilt||0)+(b.partial||0),'full',true),kpi('Validation success',b.validation_success_rate,'validation_success_rate',false,'pct'),kpi('No-code rate',b.no_code_rate,'no_code_rate',false,'pct')].join('');
 const unique=sb.unique_indexed_fixtures??sb.fixtures??0,declared=sb.declared_total??unique;const complete=sb.is_complete===true&&unique>=declared&&sb.error==null;$('health').innerHTML=`<div class="health-item"><div class="health-label">Today’s prediction run</div><div class="health-value"><span class="status ${last?.status==='success'?'ok':last?'warning':'neutral'}">${esc(last?.status||'No run')}</span></div><div class="muted">${esc(when(last?.finished_at))}</div></div><div class="health-item"><div class="health-label">SportyBet unique fixtures</div><div class="health-value">${num(unique)} / ${num(declared)}</div><span class="status ${complete?'ok':'bad'}">${complete?'Complete':'Incomplete'}</span></div><div class="health-item"><div class="health-label">System booking health</div><div class="health-value">${pct(b.success_rate)}</div><div class="muted">${num(b.attempts)} automated attempts</div></div><div class="health-item"><div class="health-label">Settlement / jobs</div><div class="health-value">${last?.failed?.length?'<span class="status bad">Attention</span>':'<span class="status ok">Healthy</span>'}</div><div class="muted">${last?.failed?.length?esc(last.failed.join(', ')):'No reported failures'}</div></div>`;
 $('health').insertAdjacentHTML('beforeend',`<div class="health-item"><div class="health-label">Analytics</div><div class="health-value"><span class="status ${s.analytics_provider?.status==='fresh'?'ok':'warning'}">${s.analytics_provider?.status==='fresh'?'Healthy':'Degraded'}</span></div><div class="muted">Diagnostics are in Analytics health.</div></div>`);$('predictionFunnel').innerHTML=funnel(s.funnels?.prediction);$('builderFunnel').innerHTML=funnel(s.funnels?.builder);$('rolloverFunnel').innerHTML=funnel(s.funnels?.rollover);$('trend').innerHTML=renderTrend(s.daily);$('topPages').innerHTML=bars(s.by_path);$('sourcesMini').innerHTML=bars(s.by_source);
 const alerts=[];if(s.analytics_provider?.status!=='fresh')alerts.push(['Analytics degraded','PostHog is unavailable or stale. Product and booking operations are unaffected.']);if(!complete)alerts.push(['Catalogue incomplete',`${num(unique)} unique of ${num(declared)} declared fixtures. Raw records: ${num(sb.raw_fetched_records)}.`]);if((b.no_code_rate||0)>.1)alerts.push(['No-code rate needs attention',`${pct(b.no_code_rate)} of automated bookings did not produce a usable code.`]);if((s.analytics_quality?.geo_coverage??1)<.7)alerts.push(['Analytics geo coverage degraded',`${pct(s.analytics_quality.geo_coverage)} of user events have trusted country metadata.`]);if(b.validation_failed)alerts.push(['Code validation failures',`${b.validation_failed} generated code(s) failed read-back validation.`]);if(last?.failed?.length)alerts.push(['Daily run incomplete',last.failed.join(', ')]);if(!alerts.length)alerts.push(['All key systems look healthy','No high-priority operational warnings in this period.']);$('alerts').innerHTML=alerts.map((a,i)=>`<div class="alert"><div class="alert-icon">${i?'!':'✓'}</div><div><strong>${esc(a[0])}</strong><p>${esc(a[1])}</p></div></div>`).join('')}
const countryNames=typeof Intl.DisplayNames==='function'?new Intl.DisplayNames([navigator.language],{type:'region'}):null;const countryLabel=code=>code==='unknown'?'Unknown':(countryNames?.of(code)||code);
function qualityCell(label,value){const cls=value==null?'neutral':value>=.9?'ok':value>=.7?'warning':'bad';return`<div class="retention-cell"><strong>${pct(value)}</strong><span>${esc(label)}</span><div class="status ${cls}">${value==null?'Awaiting data':value>=.9?'Healthy':value>=.7?'Watch':'Degraded'}</div></div>`}
function audienceTable(rows,label=x=>x){return table(['Segment','Visitors','Returning','Sessions','Prediction viewers','Builders','Code copiers','Copy conversion'],(rows||[]).map(r=>`<tr><td><strong>${esc(label(r.key))}</strong></td><td class="num">${num(r.visitors)}</td><td class="num">${num(r.returning)}</td><td class="num">${num(r.sessions)}</td><td class="num">${num(r.prediction_viewers)}</td><td class="num">${num(r.builders)}</td><td class="num">${num(r.code_copiers)}</td><td class="num">${pct(r.copy_conversion)}</td></tr>`))}
function deviceTable(rows){return table(['Device','Visitors','Prediction rate','Builder rate','Copy conversion','SportyBet open rate','Return rate'],(rows||[]).map(r=>`<tr><td><strong>${esc(r.key)}</strong></td><td class="num">${num(r.visitors)}</td><td class="num">${pct(r.prediction_view_rate)}</td><td class="num">${pct(r.builder_usage_rate)}</td><td class="num">${pct(r.copy_conversion)}</td><td class="num">${pct(r.sportybet_open_rate)}</td><td class="num">${pct(r.return_rate)}</td></tr>`))}
function renderAudience(){const s=DASH.summary,a=s.active_users||{},q=s.analytics_quality||{},pr=s.prediction_day_return||{};$('activeUsers').innerHTML=[kpi('Daily active',a.dau,'dau'),kpi('Weekly active',a.wau,'wau'),kpi('Monthly active',a.mau,'mau'),kpi('New visitors',s.totals.new_visitors,'new_visitors'),kpi('Returning',s.totals.returning_visitors,'returning_visitors',true),kpi('Prediction day return',pr.rate,'prediction_day_return',false,'pct')].join('');$('retention').innerHTML=Object.entries(s.retention||{}).map(([k,v])=>`<div class="retention-cell"><strong>${pct(v.rate)}</strong><span>${esc(k)} retention</span><div class="muted">${v.returned}/${v.eligible} eligible</div></div>`).join('');$('quality').innerHTML=[qualityCell('Geo coverage',q.geo_coverage),qualityCell('Device detection',q.device_coverage),qualityCell('OS detection',q.os_coverage),qualityCell('Browser detection',q.browser_coverage),qualityCell('Referrer attribution',q.referrer_attribution),qualityCell('Stable visitor IDs',q.stable_visitor_coverage)].join('');$('countries').innerHTML=audienceTable(s.by_country,countryLabel);$('devices').innerHTML=deviceTable(s.by_device);$('os').innerHTML=audienceTable(s.by_os);$('browsers').innerHTML=audienceTable(s.by_browser);$('traffic').innerHTML=audienceTable(s.by_source)}
function renderSporty(){const s=DASH.summary,b=s.booking,sb=s.sportybet||{};$('sportyKpis').innerHTML=[kpi('Automated attempts',b.attempts,'attempts'),kpi('Full success',b.full,'full',true),kpi('Rebuilt full',b.rebuilt,'rebuilt'),kpi('Partial',b.partial,'partial'),kpi('Validation success',b.validation_success_rate,'validation_success_rate',false,'pct'),kpi('No-code rate',b.no_code_rate,'no_code_rate',false,'pct')].join('');$('userBooking').innerHTML=[kpi('Valid code viewers',s.totals.valid_code_viewers,'valid_code_viewers'),kpi('Unique code copiers',s.totals.unique_code_copiers,'unique_code_copiers',true),kpi('Copy actions',s.totals.total_copy_actions,'total_copy_actions'),kpi('SportyBet openers',s.totals.sportybet_openers,'sportybet_openers')].join('');$('catalogue').innerHTML=`<div class="metric-list"><div class="metric-row"><strong>Declared fixtures</strong><span>${maybeNum(sb.declared_total)}</span></div><div class="metric-row"><strong>Raw fetched records</strong><span>${maybeNum(sb.raw_fetched_records??sb.fetched_total)}</span></div><div class="metric-row"><strong>Unique indexed fixtures</strong><span>${maybeNum(sb.unique_indexed_fixtures??sb.fixtures)}</span></div><div class="metric-row"><strong>Duplicates removed</strong><span>${maybeNum(sb.duplicates_removed)}</span></div><div class="metric-row"><strong>Invalid records</strong><span>${maybeNum(sb.invalid_records)}</span></div><div class="metric-row"><strong>Catalogue complete</strong><span class="status ${sb.is_complete===true?'ok':'bad'}">${sb.is_complete===true?'Yes':'No'}</span></div><div class="metric-row"><strong>Priced markets</strong><span>${maybeNum(sb.priced_markets)}</span></div><div class="metric-row"><strong>Cache age</strong><span>${sb.cache_age_hours==null?'—':sb.cache_age_hours+'h'}</span></div></div>`;$('tierBooking').innerHTML=table(['Tier','Generated','Full','Rebuilt','Partial','No code','Avg odds'],(b.by_tier||[]).map(r=>`<tr><td><strong>${esc(r.tier)}</strong></td><td class="num">${num(r.generated)}</td><td class="num">${num(r.full)}</td><td class="num">${num(r.rebuilt)}</td><td class="num">${num(r.partial)}</td><td class="num">${num((r.unavailable||0)+(r.failed||0)+(r.validation_failed||0))}</td><td class="num">${r.avg_actual_odds??'—'}</td></tr>`));$('failures').innerHTML=table(['Failure reason','Tier','Count'],(b.failures||[]).map(r=>`<tr><td>${esc(r.reason)}</td><td>${esc(r.tier||'unknown')}</td><td class="num">${num(r.count)}</td></tr>`))}
function renderProduct(){const s=DASH.summary,b=s.builder||{},bb=s.builder_backend||{};$('builderKpis').innerHTML=[kpi('Builder users',s.totals.builder_users,'builder_users'),kpi('Server requests',bb.requests,'slip_builds'),kpi('Tickets produced',bb.tickets_produced,'valid_code_viewers',true),kpi('Ticket rate',bb.ticket_rate,'code_copy_rate',false,'pct'),kpi('Average legs',b.average_legs,'average_legs'),kpi('Average actual odds',b.average_actual_odds,'actual_odds')].join('');$('targets').innerHTML=bars((bb.by_target||[]).map(r=>({key:r.target,visitors:r.requests})));$('features').innerHTML=audienceTable(s.by_product_source);const perf=Object.entries(s.prediction_performance||{});$('performance').innerHTML=table(['Tier','Settled','Won','Lost','Accuracy','ROI','Profit'],perf.map(([tier,r])=>`<tr><td><strong>${esc(tier)}</strong></td><td class="num">${num(r.settled)}</td><td class="num">${num(r.won)}</td><td class="num">${num(r.lost)}</td><td class="num">${pct(r.win_rate)}</td><td class="num">${pct(r.roi)}</td><td class="num">${r.profit??0}</td></tr>`))}
function renderAnalyticsHealth(){const s=DASH.summary,h=s.analytics_health||{},p=h.provider||{},q=h.quality||{},c=s.metric_contracts||{};$('providerHealth').innerHTML=`<div class="health-grid"><div class="health-item"><div class="health-label">Human analytics</div><div class="health-value">${sourceLine(p)}</div><div class="muted">${esc(p.reason||'PostHog Query API responding')}</div></div><div class="health-item"><div class="health-label">Backend facts</div><div class="health-value">${sourceLine(s.sources?.backend_facts)}</div></div><div class="health-item"><div class="health-label">Dual validation ends</div><div class="health-value">${esc(h.dual_write_until||'not set')}</div><div class="muted">Migration remains open until live events are verified.</div></div></div>`;$('quality').innerHTML=[qualityCell('Geo coverage',q.geo_coverage),qualityCell('Device detection',q.device_coverage),qualityCell('OS detection',q.os_coverage),qualityCell('Browser detection',q.browser_coverage),qualityCell('Referrer attribution',q.referrer_attribution),qualityCell('Stable visitor IDs',q.stable_visitor_coverage)].join('');$('rateContracts').innerHTML=table(['Metric','Numerator','Denominator','Rate','Sample'],Object.entries(c).map(([name,v])=>`<tr><td>${esc(name)}</td><td class="num">${num(v.numerator)}</td><td class="num">${num(v.denominator)}</td><td class="num">${pct(v.rate)}</td><td><span class="status ${v.sample_status==='normal'?'ok':'warning'}">${esc(v.sample_status)}</span></td></tr>`))}
function dateISO(d){return d.toISOString().slice(0,10)}
async function loadDashboard(){const active=document.querySelector('.range button.active');const days=active?.dataset.days||'1';let q='?days='+days;if(days==='yesterday'){const d=new Date();d.setUTCDate(d.getUTCDate()-1);q=`?start=${dateISO(d)}&end=${dateISO(d)}`}if(days==='custom'){if(!$('dateStart').value||!$('dateEnd').value)return;q=`?start=${$('dateStart').value}&end=${$('dateEnd').value}`}try{const [d,s]=await Promise.all([api('/analytics'+q),api('/status')]);DASH=d;SETTINGS=s.settings||{};$('period').textContent=`${d.summary.start} → ${d.summary.end}`;renderOverview();renderAudience();renderSporty();renderProduct();renderAnalyticsHealth()}catch(e){$('toast').textContent=e.message;$('toast').classList.remove('hidden')}}
async function loadHomeCampaign(){
  const status=$('homeCampaignStatus');
  if(!status)return;
  try {
    const d=await api('/homepage-campaign'),c=d.campaign||{};
    for(const key of ['eyebrow','headline','description','cta_text','cta_path','starts_on','ends_on','source_url']){
      const el=$('campaign_'+key);
      if(el)el.value=c[key]||'';
    }
    $('campaign_enabled').checked=Boolean(c.enabled);
    $('campaign_reviewed').checked=Boolean(c.reviewed);
    status.textContent=c.enabled
      ? 'Scheduled: '+(c.starts_on||'—')+' to '+(c.ends_on||'—')+' (WAT). Expiry automatically restores fixture-driven hero.'
      : 'Inactive. Upcoming verified fixture context remains the automatic fallback.';
  }catch(e){status.textContent=e.message}
}
async function saveHomeCampaign(){
  const status=$('homeCampaignStatus'),campaign={};
  for(const key of ['eyebrow','headline','description','cta_text','cta_path','starts_on','ends_on','source_url']){
    campaign[key]=($('campaign_'+key)?.value||'').trim();
  }
  campaign.enabled=$('campaign_enabled').checked;
  campaign.reviewed=$('campaign_reviewed').checked;
  status.textContent='Saving reviewed website campaign…';
  try{
    await api('/homepage-campaign',{method:'POST',body:JSON.stringify(campaign)});
    status.textContent=campaign.enabled
      ? 'Saved. The homepage displays this campaign only during its WAT date range.'
      : 'Campaign disabled. The homepage uses fixture-driven context.';
  }catch(e){status.textContent=e.message}
}
async function loadContent(){const p=$('fPlatform').value,st=$('fStatus').value;try{const d=await api('/content?limit=400'+(p?'&platform='+p:'')+(st?'&status='+st:''));$('contentTable').innerHTML=table(['Template','Platform','Status','Date','Actions'],d.content.map(c=>`<tr><td>${esc(c.template)}</td><td>${esc(c.platform)}</td><td><span class="tag ${esc(c.status)}">${esc(c.status)}</span></td><td>${esc(c.publish_date)}</td><td class="row wrap"><button class="btn" data-act="preview" data-id="${c.id}">View</button>${c.status==='DRAFT'?`<button class="btn" data-act="approve" data-id="${c.id}">Approve</button>`:''}${!['instagram','facebook','tiktok','youtube','x'].includes(c.platform)&&c.status!=='PUBLISHED'?`<button class="btn btn-primary" data-act="publish" data-id="${c.id}">Publish</button>`:''}</td></tr>`))}catch(e){$('contentTable').innerHTML=empty(e.message)}}
async function preview(id){const d=await api('/content?limit=400'),c=d.content.find(x=>x.id===id);if(!c)return;const p=c.payload||{};$('previewBody').textContent=p.text||p.caption||JSON.stringify(p,null,2);$('preview').classList.remove('hidden')}
async function act(id,what){try{await api(`/content/${id}/${what}`,{method:'POST'});loadContent()}catch(e){alert(e.message)}}
async function generate(publish){try{const d=await api('/generate?publish='+publish,{method:'POST'}),r=d.report;alert(`Generated ${r.generated}; stored ${r.stored}; published ${r.published.length}; failed ${r.failed.length}.`);loadContent()}catch(e){alert(e.message)}}
async function retry(){try{const d=await api('/retry',{method:'POST'});alert(`Retried ${d.attempted}; recovered ${d.recovered}.`);loadPubs()}catch(e){alert(e.message)}}
async function loadPubs(){try{const d=await api('/publications?limit=300');$('pubTable').innerHTML=table(['Date','Channel','Template','Status','Tries','Detail'],d.publications.map(p=>`<tr><td>${esc(p.publish_date)}</td><td>${esc(p.channel)}</td><td>${esc(p.template)}</td><td><span class="tag ${esc(p.status)}">${esc(p.status)}</span></td><td class="num">${p.attempts}</td><td class="muted">${esc(p.last_error?.slice(0,80)||p.external_id||'')}</td></tr>`))}catch(e){$('pubTable').innerHTML=empty(e.message)}}
async function loadSettings(){try{const d=await api('/settings');SETTINGS=d.settings;const toggles=(obj,prefix)=>Object.entries(obj||{}).map(([k,v])=>`<div class="switch"><span>${esc(k)}</span><input type="checkbox" id="${prefix}_${esc(k)}" ${v?'checked':''}></div>`).join('');$('engineToggle').innerHTML=`<div class="switch"><span>Growth Engine enabled</span><input type="checkbox" id="s_engine" ${SETTINGS.engine_enabled?'checked':''}></div>`;$('channelToggles').innerHTML=toggles(SETTINGS.channel_enabled,'ch');$('autoToggles').innerHTML=toggles(SETTINGS.channel_auto_publish,'auto');$('scheduleFields').innerHTML=Object.entries(SETTINGS.schedule||{}).map(([k,v])=>`<div class="switch"><span>${esc(k)}</span><input class="field" id="sch_${esc(k)}" value="${esc(v)}"></div>`).join('')}catch(e){}}
async function saveSettings(){const ch={},auto={},sch={};Object.keys(SETTINGS.channel_enabled||{}).forEach(k=>ch[k]=$('ch_'+k).checked);Object.keys(SETTINGS.channel_auto_publish||{}).forEach(k=>auto[k]=$('auto_'+k).checked);Object.keys(SETTINGS.schedule||{}).forEach(k=>sch[k]=$('sch_'+k).value.trim());try{await api('/settings',{method:'POST',body:JSON.stringify({engine_enabled:$('s_engine').checked,channel_enabled:ch,channel_auto_publish:auto,schedule:sch})});$('settingsMsg').textContent='Settings saved'}catch(e){$('settingsMsg').textContent=e.message}}
async function loadRefs(){try{const d=await api('/referrals');$('refTable').innerHTML=table(['Code','Name','Link'],d.referrals.map(r=>{const link=`https://www.betsightly.com/predictions?utm_source=referral&utm_medium=referral&utm_campaign=creator&ref=${encodeURIComponent(r.code)}`;return`<tr><td><code>${esc(r.code)}</code></td><td>${esc(r.name||'')}</td><td>${esc(link)}</td></tr>`}))}catch(e){}}
async function addRef(){try{await api('/referrals',{method:'POST',body:JSON.stringify({code:$('refCode').value,name:$('refName').value})});$('refCode').value=$('refName').value='';loadRefs()}catch(e){$('refErr').textContent=e.message}}
async function loadManual(){
 const el=$('manualPublished');
 if(el){el.setAttribute('aria-busy','true');el.innerHTML='<div class="empty"><span class="admin-inline-spinner" aria-hidden="true"></span> Checking saved editorial tickets…</div>';}
 try{
  const d=await api('/manual-tiers'),r=d.rollover||{};
  $('manualRolloverStatus').textContent=r.allowed
   ? 'Rollover Day '+num(r.day_number)+' is eligible for '+esc(r.date)+'. Choose 2.00x–4.00x from verified, unused fixtures.'
   : (r.reason||'Rollover status unavailable; publishing is blocked.');
  const rows=Object.values(d.published||{});
  el.innerHTML=rows.length?table(['Tier','Games','Verified odds','Share code'],rows.map(r=>`<tr><td>${esc(r.tier)}</td><td>${num(r.leg_count)}</td><td>${esc(r.total_odds)}x</td><td><code>${esc(r.share_code||'unavailable')}</code></td></tr>`)):empty('No manual tickets published today. All official records remain unchanged.');
  return d;
 }catch(e){el.textContent='Could not load saved tickets: '+e.message;return null;}
 finally{if(el)el.setAttribute('aria-busy','false')}
}
function syncManualTier(){
 const tier=$('manualTier').value;
 const replacementEligible=['2_odds','5_odds','10_odds','over_1_5'].includes(tier);
 const replace=$('manualReplaceOfficialDisplay');
 if(!replacementEligible)replace.checked=false;
 replace.closest('label').classList.toggle('hidden',!replacementEligible);
 $('manualRolloverStatus').classList.toggle('hidden',tier!=='rollover');
 manualImportReview=null;
 manualImportedCode=null;
 manualPreviewConfirmed=null;
 if(!manualBusyOperation){
  manualStage(0,'idle','Ready to import',
   'Choose an input: SportyBet booking code, CSV or event ID / market rows. No publication has been attempted.');
 }
 manualUpdatePublishAvailability();
}
let manualImportReview=null;
let manualImportedCode=null;
let manualPreviewConfirmed=null;
let manualBusyOperation=null;
let manualPublishUncertain=false;
let manualUncertainTier=null;
let manualStageNumber=0;
function manualStage(step,state,title,detail){
 const el=$('manualWorkflow');
 if(!el)return;
 manualStageNumber=step;
 el.dataset.state=state;
 el.setAttribute('aria-busy',state==='busy'?'true':'false');
 $('manualWorkflowTitle').textContent=title;
 $('manualWorkflowDetail').textContent=detail||'';
 const icon=$('manualWorkflowIcon');
 if(icon)icon.textContent=state==='success'?'✓':state==='error'?'!':'◎';
 document.querySelectorAll('#manualWorkflow [data-manual-step]').forEach(node=>{
  const index=Number(node.dataset.manualStep);
  node.dataset.stepState=index<step?'done':index===step?
   (state==='busy'?'active':state==='success'?'done':'active'):'future';
 });
}
function manualFormLock(lock){
 const controls=document.querySelectorAll('#page-manual [data-act^="manual-"],#manualTier,#manualShareCode,#manualConvertSpecial,#manualLines,#manualReplaceOfficialDisplay,#manualFile');
 controls.forEach(node=>{
  if(lock){
   node.dataset.beforeBusyDisabled=node.disabled?'1':'0';
   node.disabled=true;
  }else{
   node.disabled=node.dataset.beforeBusyDisabled==='1';
   delete node.dataset.beforeBusyDisabled;
  }
 });
 const editor=$('manualEditor');
 if(editor)editor.setAttribute('aria-busy',lock?'true':'false');
}
function manualUpdatePublishAvailability(){
 const request=manualRequest();
 const confirmed=Boolean(manualPreviewConfirmed&&
  manualPreviewConfirmed.tier===request.tier&&
  manualPreviewConfirmed.lines===request.lines&&
  manualPreviewConfirmed.replace_official_display===request.replace_official_display);
 const imported=Boolean(confirmed&&manualImportedCode&&
  manualImportedCode.tier===request.tier&&
  manualImportedCode.lines===request.lines&&
  manualImportedCode.code===$('manualShareCode').value.trim()&&
  !$('manualConvertSpecial').checked);
 const locked=Boolean(manualBusyOperation||manualPublishUncertain||manualImportReview);
 const importedButton=$('manualCodePublish');
 const reviewedButton=document.querySelector('[data-act="manual-publish"]');
 if(importedButton)importedButton.disabled=locked||!imported;
 if(reviewedButton)reviewedButton.disabled=locked||!confirmed;
}
async function manualWithProgress(name,stage,description,fn){
 // Synchronous latch prevents double submission even before the DOM repaints.
 if(manualBusyOperation)return;
 if(manualPublishUncertain && (name==='publish'||name==='publish-imported')){
  manualStage(5,'error','Publication confirmation required',
   'The last request had an uncertain response. Refresh saved tickets before trying to publish again.');
  return;
 }
 manualBusyOperation=name;
 manualStage(stage,'busy',description,
  'Contacting BetSightly securely. Leave this page open; do not submit another request.');
 manualFormLock(true);
 try{
  await fn();
 }catch(error){
  $('manualErr').textContent=error.message||'Request failed. Check the saved tickets before retrying.';
  manualStage(stage,'error',description+' failed',error.message||'No change was confirmed.');
 }finally{
  manualBusyOperation=null;
  manualFormLock(false);
  manualUpdatePublishAvailability();
  if($('manualWorkflow')?.dataset.state==='busy')
   manualStage(stage,'ready','Ready for the next step',
    'The request finished. Review the message above and verify the saved code before proceeding.');
 }
}
function manualInvalidatePreview(){
 if(manualBusyOperation)return;
 manualPreviewConfirmed=null;
 manualUpdatePublishAvailability();
 if(!manualImportReview)
  manualStage(2,'ready','Selections edited — preview again',
   'The previous price check is no longer valid. Run Check prices / preview before publishing.');
}
async function manualRefreshPublished(){
 const tier=manualUncertainTier||$('manualTier').value;
 manualStage(5,'busy','Checking published ticket','Reading saved manual tickets, without attempting another publish.');
 try{
  const result=await loadManual();
  if(!result)throw Error('The server has not confirmed the current saved tickets.');
  const ticket=(result.published||{})[tier];
  if(ticket?.share_code){
   manualPublishUncertain=false;manualUncertainTier=null;
   manualStage(5,'success','Saved publication found',
    tier+' is stored with verified code '+ticket.share_code+'. Do not submit it again.');
  }else{
   manualPublishUncertain=false;manualUncertainTier=null;
   manualPreviewConfirmed=null;
   manualStage(2,'ready','No saved ticket found for '+tier,
    'The current database has no manual ticket for this tier. Import and verify again before a new submission.');
  }
 }catch(e){
  manualStage(5,'error','Could not verify saved tickets',
   'Publication state remains uncertain. Do not send a second publish request until the database responds.');
 }
}
const REGULAR_MANUAL_MARKETS=[
  ['home_win','Home win'],['draw','Draw'],['away_win','Away win'],
  ['home_or_draw','Home or draw'],['away_or_draw','Away or draw'],
  ['dnb_home','Home draw no bet'],['dnb_away','Away draw no bet'],
  ['over_0_5','Over 0.5 (either team scores)'],
  ['home_over_0_5','Home team Over 0.5'],['away_over_0_5','Away team Over 0.5'],
  ['home_over_1_5','Home team Over 1.5 (2+ goals)'],
  ['away_over_1_5','Away team Over 1.5 (2+ goals)'],
  ['over_1_5','Over 1.5'],['over_2_5','Over 2.5'],
  ['over_3_5','Over 3.5'],['over_4_5','Over 4.5'],
  ['under_2_5','Under 2.5'],['under_4_5','Under 4.5'],
  ['btts_yes','Both teams score — Yes'],['btts_no','Both teams score — No']
];
async function manualImportCode(){
 const msg=$('manualErr');msg.textContent='';
 manualImportedCode=null;manualPreviewConfirmed=null;
 $('manualCodePublish').disabled=true;
 const code=$('manualShareCode').value.trim();
 if(!code){msg.textContent='Enter a SportyBet booking code.';return}
 const convert=$('manualConvertSpecial').checked;
 const button=document.querySelector('[data-act="manual-import-code"]');
 if(button){button.disabled=true;button.textContent='Reading code…'}
 const existing=$('manualPreview').innerHTML;
 $('manualPreview').textContent='Reading all selections from SportyBet. Import does not publish a ticket.';
 manualImportReview=null;
 try{
  const d=await api('/manual-tiers/import-code',{
   method:'POST',body:JSON.stringify({tier:$('manualTier').value,code,convert_special:convert})
  });
  const converted=d.converted_features||[];
  const changes=converted.length
   ?'<p class="note" role="alert"><strong>Changed '+num(converted.length)+' special markets:</strong> '+converted.map(x=>esc(x.event_id)+' '+esc(x.from)+' → '+esc(x.to)).join('; ')+'. Original early payouts are NOT preserved.</p>':'';
  const warnings=(d.warnings||[]).map(x=>'<li>'+esc(x)+'</li>').join('');
  const needsReview=d.status==='NEEDS_MANUAL_REVIEW'&&d.unresolved_count>0;
  if(!needsReview)$('manualLines').value=d.lines;
  else manualImportReview=d;
  if(!needsReview && !converted.length && d.status==='IMPORTED_NOT_PUBLISHED')
   manualImportedCode={code,tier:d.tier,lines:d.lines,legs:d.original_leg_count};
  const marketChoices=d.tier==='over_1_5'
   ?REGULAR_MANUAL_MARKETS.filter(pair=>
     /^over_[0-4]_5$/.test(pair[0]) ||
     /^(home|away)_over_(0|1)_5$/.test(pair[0]) ||
     pair[0]==='btts_yes')
   :REGULAR_MANUAL_MARKETS;
  const rows=d.games.map((g,i)=>{
   if(!g.requires_review)return '<tr><td>'+esc(g.sportybet_event_id)+'</td><td>'+esc(g.market)+'</td><td>Decoded</td></tr>';
   const options='<option value="">Choose regular market — required</option>'+
    marketChoices.map(pair=>'<option value="'+pair[0]+'">'+esc(pair[1])+'</option>').join('');
   const original=[g.reported_market,g.reported_outcome].filter(Boolean).join(' · ');
   return '<tr><td>'+esc(g.sportybet_event_id)+'</td><td><select class="field" data-manual-review-index="'+i+'" aria-label="Regular market for event '+esc(g.sportybet_event_id)+'">'+options+'</select></td><td><strong>Admin choice required</strong><small style="display:block;color:var(--muted)">'+esc(original||'SportyBet did not provide a recognizable standard market')+'</small></td></tr>';
  });
  const review=needsReview
   ?'<p class="note" role="alert"><strong>'+num(d.unresolved_count)+' market(s) need your explicit choice.</strong> SportyBet provided a non-standard outcome/market ID. Choose the regular equivalent for every unresolved match from your original betslip. BetSightly will not guess or drop a leg. Existing editor rows are preserved until you apply this review.</p>'
    +table(['SportyBet match ID','Regular market for new ticket','Original market information'],rows)
    +'<div class="row wrap" style="margin-top:14px"><button class="btn btn-primary" type="button" data-act="manual-apply-import-review">Apply reviewed markets</button><button class="btn" type="button" data-act="manual-cancel-import-review">Cancel import review</button></div>'
   :'<p>Next: click <strong>Check prices / preview</strong>. This checks exact SportyBet prices, kickoffs, tier rules and availability before a fresh verified code can be published.</p>'
    +table(['SportyBet match ID','Decoded regular market','Result'],rows);
  $('manualPreview').innerHTML='<p><strong>Code read: '+num(d.original_leg_count)+' selections.</strong> Nothing has been published. '+(d.total_odds!=null?'Original code price: '+esc(d.total_odds)+'x (NOT a current verified price).':'')+'</p>'+changes+(warnings?'<div role="status"><strong>Review before publishing:</strong><ul>'+warnings+'</ul></div>':'')+'<p class="muted">'+esc(d.note||'Special options do not transfer to regular markets.')+'</p>'+review;
 }catch(e){
  msg.textContent=e.message;
  $('manualPreview').innerHTML=existing||'Import failed. Your previous manual selections are unchanged.';
 }finally{
  if(button){button.disabled=false;button.textContent='Find games from code'}
 }
}
function manualApplyImportReview(){
 const d=manualImportReview;
 if(!d)return;
 const msg=$('manualErr');msg.textContent='';
 if($('manualTier').value!==d.tier){msg.textContent='Select '+d.tier+' as the tier again or cancel this review.';return}
 const rows=[];
 for(let i=0;i<d.games.length;i++){
  const game=d.games[i];let market=game.market;
  if(game.requires_review){
   market=document.querySelector('[data-manual-review-index="'+i+'"]')?.value||'';
   if(!market){msg.textContent='Choose a regular market for event '+game.sportybet_event_id+' before continuing.';return}
  }
  rows.push(game.sportybet_event_id+','+market);
 }
 if(rows.length!==d.original_leg_count){
  msg.textContent='The complete original ticket was not recovered. Import refused.';return;
 }
 if(!window.confirm('Convert all '+rows.length+' selections into a DIFFERENT standard-market ticket? 1UP, 2UP, EarlyGoals, Flexi and promotions will NOT be preserved. The new ticket must be previewed and verified.'))return;
 $('manualLines').value=rows.join('\n');
 manualImportReview=null;
 manualImportedCode=null;manualPreviewConfirmed=null;
 $('manualCodePublish').disabled=true;
 $('manualPreview').textContent='All '+rows.length+' selections prepared as ordinary markets by explicit admin review. Promo features are NOT preserved. Click Check prices / preview next; the original price is not guaranteed.';
}
function manualCancelImportReview(){
 manualImportReview=null;
 $('manualErr').textContent='';
 $('manualPreview').textContent='Import review cancelled. Previous editor selections are unchanged.';
}
function manualRequest(){
 return {tier:$('manualTier').value,lines:$('manualLines').value,
         replace_official_display:$('manualReplaceOfficialDisplay').checked};
}
function manualRenderSuccess(d, originalCode){
 const changed=originalCode && d.share_code!==originalCode;
 $('manualPreview').textContent='Published '+d.tier+' — '+d.leg_count+' games, '+d.total_odds+
  'x, verified SportyBet code '+d.share_code+
  (changed?' (new verified code; original input '+originalCode+' is not the displayed ticket)':'')+
  '. The original model record is still available in Results.'+
  ((d.cross_tier_warnings||[]).length?
   ' Shared fixtures with other tiers: '+d.cross_tier_warnings.map(w=>w.fixture).join('; ')+
   '. Outcomes across tickets can be correlated.':'');
 $('manualErr').textContent='';
}
async function manualPreview(){
 const msg=$('manualErr');msg.textContent='';
 manualPreviewConfirmed=null;
 $('manualCodePublish').disabled=true;
 if(manualImportReview){msg.textContent='Finish or cancel the import review first. No partial ticket can be previewed.';return}
 const request=manualRequest();
 if(!request.lines.trim()){msg.textContent='First click Find games from code to load every selection, or enter event ID,market rows manually. Nothing was published.';return}
 try{
  const d=await api('/manual-tiers/preview',{method:'POST',body:JSON.stringify(request)});
  const repeats=d.cross_tier_warnings||[];
  const warningHtml=repeats.length?
   '<div class="note" role="status"><strong>Shared fixtures (allowed for manual tickets):</strong><ul>'+
   repeats.map(w=>'<li>'+esc(w.fixture)+' — '+esc(w.message)+'</li>').join('')+
   '</ul><small>These tickets can win or lose together. The original automatic tickets and their results remain unchanged.</small></div>':'';
  $('manualPreview').innerHTML='<p><strong>Bookmaker-priced preview:</strong> '+esc(d.total_odds)+'x across '+num(d.games.length)+' legs. No code created yet.</p>'+
   warningHtml+table(['Fixture','Market','Price'],d.games.map(g=>`<tr><td>${esc(g.home_team)} v ${esc(g.away_team)}</td><td>${esc(g.market)}</td><td>${esc(g.odds)}x</td></tr>`));
  manualPreviewConfirmed={...request};
  if(manualImportedCode && manualImportedCode.tier===request.tier && manualImportedCode.lines===request.lines &&
     manualImportedCode.code===$('manualShareCode').value.trim() && !$('manualConvertSpecial').checked)
     $('manualCodePublish').disabled=false;
 }catch(e){
  msg.textContent=e.message+
   (/HTTP (?:502|503|504)|Network request failed/i.test(e.message)?
    '. Preview is read-only; no new ticket was published by this preview. Retry after the server recovers.':'');
  $('manualPreview').textContent='';
 }
}
async function reconcileManualPublishAfterError(tier, failure){
 // A proxy 502 may arrive AFTER a committed bookmaker-verified publication.
 // GET is read-only. Never automatically send the POST again on an unclear
 // result, or assume a 502 means that the database transaction was rolled back.
 const transient=/HTTP (?:502|503|504)|Network request failed/i.test(failure.message||'');
 if(!transient)return false;
 $('manualErr').textContent='Server connection interrupted. Checking whether the ticket was saved before retrying…';
 const delays=[0,1300,2700,4200];
 for(const delay of delays){
  if(delay)await new Promise(resolve=>setTimeout(resolve,delay));
  try{
   const result=await api('/manual-tiers');
   const existing=(result.published||{})[tier];
   if(existing && existing.share_code){
    $('manualErr').textContent='The server interrupted your response, but a '+tier+
     ' manual ticket exists in the database: '+existing.leg_count+' legs, verified code '+
     existing.share_code+' ('+existing.total_odds+'x). Review it in Today’s editorial tickets. Do NOT publish this tier again.';
    await loadManual();
    return true;
   }
   $('manualErr').textContent='The server is reachable but no manual '+tier+
    ' ticket is recorded. You may re-import and preview the code before another publication attempt.';
   return false;
  }catch(e){
   // During a restart the read-only status request can also fail. Try again
   // instead of telling the user that no ticket exists.
  }
 }
 $('manualErr').textContent='The server could not confirm whether '+tier+
  ' was published. Refresh Today’s editorial tickets when the server recovers. Do NOT submit the same code twice until you verify the existing record.';
 return false;
}
async function manualPublishImported(){
 const msg=$('manualErr');msg.textContent='';
 const request=manualRequest();
 const imported=manualImportedCode;
 if(!imported || !manualPreviewConfirmed || imported.tier!==request.tier ||
    imported.lines!==request.lines || imported.code!==$('manualShareCode').value.trim() ||
    manualPreviewConfirmed.lines!==request.lines ||
    manualPreviewConfirmed.replace_official_display!==request.replace_official_display ||
    $('manualConvertSpecial').checked){
  msg.textContent='First import the exact SportyBet code and run Check prices / preview successfully. Review special markets separately.';
  return;
 }
 if(!window.confirm('Publish ALL '+imported.legs+' verified selections for '+request.tier+
  (request.replace_official_display?' as a NEW displayed editorial ticket, preserving original model results?':' as a new editorial ticket?')+
  ' A different bookmaker share code or current odds may be returned.'))return;
 const button=$('manualCodePublish');button.disabled=true;button.textContent='Verifying full code…';
 try{
  const d=await api('/manual-tiers/publish-imported',{method:'POST',body:JSON.stringify({
   tier:request.tier,code:imported.code,replace_official_display:request.replace_official_display
  })});
  manualRenderSuccess(d,imported.code);
  manualImportedCode=null;manualPreviewConfirmed=null;
  await loadManual();
 }catch(e){
  const handled=await reconcileManualPublishAfterError(request.tier,e);
  if(!handled && !msg.textContent)msg.textContent=e.message;
 }
 finally{button.textContent='Publish verified imported code'}
}
async function manualPublish(){
 const msg=$('manualErr');msg.textContent='';
 if(manualImportReview){msg.textContent='Finish or cancel the special-market import review before publishing.';return}
 const request=manualRequest();
 if(!request.lines.trim()){msg.textContent='Nothing to publish. Click Find games from code, then Check prices / preview first.';return}
 if(!manualPreviewConfirmed || manualPreviewConfirmed.tier!==request.tier ||
    manualPreviewConfirmed.lines!==request.lines ||
    manualPreviewConfirmed.replace_official_display!==request.replace_official_display){
  msg.textContent='Please check current SportyBet prices with Check prices / preview before publishing.';return;
 }
 if(!window.confirm(request.replace_official_display?
  'Replace the PUBLIC '+request.tier+' display with this NEW admin-curated ticket? The original model selection, code and Results remain unchanged.':
  'Publish this reviewed admin-curated ticket only if full SportyBet readback succeeds?'))return;
 try{
  const d=await api('/manual-tiers/publish',{method:'POST',body:JSON.stringify(request)});
  manualRenderSuccess(d,'');manualImportedCode=null;manualPreviewConfirmed=null;
  $('manualCodePublish').disabled=true;
  await loadManual();
 }catch(e){
  const handled=await reconcileManualPublishAfterError(request.tier,e);
  if(!handled && !msg.textContent)msg.textContent=e.message;
 }
}
async function manualFile(event){const file=event.target.files?.[0];if(!file)return;if(file.size>16000){$('manualErr').textContent='File too large (16 KB max).';return}const source=await file.text();manualImportReview=null;$('manualLines').value=source.slice(0,6000);$('manualPreview').textContent='CSV loaded. Click Check prices / preview before publishing.';event.target.value=''}
const ACTIONS={login,logout,retry,
 'manual-import-code':()=>manualWithProgress('import',1,'Reading SportyBet code',manualImportCode),
 'manual-publish-imported':()=>manualWithProgress('publish-imported',4,'Publishing imported code',manualPublishImported),
 'manual-apply-import-review':manualApplyImportReview,
 'manual-cancel-import-review':manualCancelImportReview,
 'manual-preview':()=>manualWithProgress('preview',3,'Checking live market prices',manualPreview),
 'manual-publish':()=>manualWithProgress('publish',4,'Publishing reviewed selections',manualPublish),
 'manual-refresh':()=>manualWithProgress('refresh',5,'Refreshing saved tickets',manualRefreshPublished),'generate':()=>generate(false),'generate-publish':()=>generate(true),'save-settings':saveSettings,'save-home-campaign':saveHomeCampaign,'add-ref':addRef,preview:e=>preview(Number(e.dataset.id)),approve:e=>act(Number(e.dataset.id),'approve'),publish:e=>act(Number(e.dataset.id),'publish'),'menu':()=>$('side').classList.toggle('open'),'apply-range':loadDashboard};
document.addEventListener('click',e=>{const el=e.target.closest('[data-act],[data-page],[data-days]');if(!el)return;if(el.dataset.page){nav(el.dataset.page,el);return}if(el.dataset.days){document.querySelectorAll('.range button').forEach(b=>b.classList.remove('active'));el.classList.add('active');$('customDates').classList.toggle('hidden',el.dataset.days!=='custom');if(el.dataset.days!=='custom')loadDashboard();return}const fn=ACTIONS[el.dataset.act];if(fn){e.preventDefault();if(manualBusyOperation&&el.dataset.act?.startsWith('manual-'))return;fn(el)}});
document.addEventListener('change',e=>{if(e.target.dataset.change==='content')loadContent();if(e.target.id==='manualFile')manualWithProgress('file',1,'Reading CSV selections',()=>manualFile(e));if(e.target.id==='manualTier')syncManualTier();if(['manualReplaceOfficialDisplay','manualConvertSpecial'].includes(e.target.id))manualInvalidatePreview()});
document.addEventListener('input',e=>{
 if(e.target.id==='manualShareCode'){
  manualImportedCode=null;manualPreviewConfirmed=null;
  manualInvalidatePreview();
 } else if(e.target.id==='manualLines'){
  manualInvalidatePreview();
 }
});$('pw').addEventListener('keydown',e=>{if(e.key==='Enter')login()});
async function boot(){$('today').textContent=new Date().toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'short'});await loadDashboard();const s=SETTINGS.channel_enabled||{},sel=$('fPlatform');if(sel.options.length===1)Object.keys(s).forEach(ch=>sel.add(new Option(ch,ch)))}
(async()=>{try{const c=await(await fetch(API+'/admin/config')).json();if(!c.configured)$('cfgNote').textContent='Admin login is not configured on this server.'}catch(e){}try{await api('/admin/me');show('app');boot()}catch(e){show('login')}})();
"""

ADMIN_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="#07100e"><title>BetSightly Command Center</title><link rel="stylesheet" href="/admin/app.css"></head><body>
<section id="login" class="login-shell"><div class="login-card"><div class="brand"><span class="brand-mark">B</span><span>BetSightly</span></div><h1>Command center</h1><p>Product growth, prediction performance and SportyBet operations in one place.</p><input id="pw" class="field" type="password" placeholder="Admin password" autocomplete="current-password"><p id="loginErr" class="error"></p><button class="btn btn-primary btn-wide" data-act="login">Enter dashboard</button><p id="cfgNote" class="muted"></p></div></section>
<div id="app" class="shell hidden"><aside id="side" class="sidebar"><div class="brand"><span class="brand-mark">B</span><span>BetSightly</span></div><div class="nav-label">Command center</div><nav class="nav"><button class="active" data-page="overview"><span class="nav-icon">◫</span>Overview</button><button data-page="audience"><span class="nav-icon">◎</span>Users & retention</button><button data-page="product"><span class="nav-icon">◇</span>Product & predictions</button><button data-page="sporty"><span class="nav-icon">S</span>SportyBet</button></nav><div class="nav-label">Operations</div><nav class="nav"><button data-page="analytics-health"><span class="nav-icon">♥</span>Analytics health</button><button data-page="content"><span class="nav-icon">✦</span>Content</button><button data-page="publishing"><span class="nav-icon">↗</span>Publishing</button><button data-page="manual"><span class="nav-icon">▤</span>Manual picks</button><button data-page="referrals"><span class="nav-icon">⌁</span>Referrals</button><button data-page="settings"><span class="nav-icon">⚙</span>Settings</button></nav><div class="sidebar-foot"><div class="live"><span class="dot"></span>Protected admin session</div><button class="btn btn-ghost btn-danger btn-wide" data-act="logout">Sign out</button></div></aside>
<div class="workspace"><header class="topbar"><div class="row"><button class="btn mobile-toggle" data-act="menu">☰</button><div class="topbar-title"><strong>Operations dashboard</strong><span id="today"></span></div></div><div class="actions"><span id="period" class="muted"></span><button class="btn desktop-action" data-act="generate">Generate content</button><button class="btn btn-primary desktop-action" data-act="generate-publish">Generate + publish</button></div></header><div id="toast" class="note hidden"></div>
<main>
<section id="page-overview" class="page active"><div class="page-head"><div><p class="eyebrow">Business overview</p><h1>Today at BetSightly</h1><p>Usage, conversion and operational health—without vanity metrics.</p></div><div><div class="range"><button class="active" data-days="1">Today</button><button data-days="yesterday">Yesterday</button><button data-days="7">7 days</button><button data-days="30">30 days</button><button data-days="90">90 days</button><button data-days="custom">Custom</button></div><div id="customDates" class="row hidden"><input id="dateStart" class="field" type="date"><input id="dateEnd" class="field" type="date"><button class="btn" data-act="apply-range">Apply</button></div></div></div>
<div class="section"><div class="section-head"><h2>Today’s health</h2><p>Can customers use the product right now?</p></div><div id="health" class="card card-flush health-grid"></div></div>
<div class="section"><div class="section-head"><h2>Audience</h2><p>Actual user activity only</p></div><div id="audienceKpis" class="grid kpis"></div></div>
<div class="section"><div class="section-head"><h2>Product engagement</h2><p>Unique people and valid-code conversion</p></div><div id="engagementKpis" class="grid kpis"></div></div>
<div class="section"><div class="section-head"><h2>Operational health</h2><p>Automated backend generation—not user attempts</p></div><div id="systemKpis" class="grid kpis"></div></div>
<div class="grid three section"><article class="card"><div class="card-title"><h3>Prediction funnel</h3><span class="muted">Unique user progression</span></div><div id="predictionFunnel" class="funnel"></div></article><article class="card"><div class="card-title"><h3>Builder funnel</h3></div><div id="builderFunnel" class="funnel"></div></article><article class="card"><div class="card-title"><h3>Rollover funnel</h3></div><div id="rolloverFunnel" class="funnel"></div></article><article class="card"><div class="card-title"><h3>Actionable alerts</h3></div><div id="alerts"></div></article></div>
<div class="grid three section"><article class="card span-2"><div class="card-title"><h3>Visitor trend</h3><div class="legend"><span>● Visitors</span></div></div><div id="trend"></div></article><article class="card"><div class="card-title"><h3>Top product areas</h3></div><div id="topPages"></div></article><article class="card"><div class="card-title"><h3>Traffic sources</h3></div><div id="sourcesMini"></div></article></div></section>
<section id="page-audience" class="page"><div class="page-head"><div><p class="eyebrow">Audience intelligence</p><h1>Users & retention</h1><p>Do people return for tomorrow’s predictions?</p></div></div><div id="activeUsers" class="grid kpis"></div><div class="section"><div class="section-head"><h2>Retention cohorts</h2><p>Privacy-safe browser identifier; anonymous and approximate.</p></div><div class="card"><div id="retention" class="retention"></div></div></div><div class="section"><div class="section-head"><h2>Countries</h2><p>Provider-enriched geography; no GPS.</p></div><div id="countries" class="card card-flush"></div></div><div class="section"><div class="section-head"><h2>Traffic-source quality</h2><p>UTM and first-session referrer attribution</p></div><div id="traffic" class="card card-flush"></div></div><div class="section"><div class="section-head"><h2>Mobile quality</h2><p>Conversion and return behaviour by device</p></div><div id="devices" class="card card-flush"></div></div><div class="grid two section"><article class="card card-flush"><div class="card-title"><h3>Operating systems</h3></div><div id="os"></div></article><article class="card card-flush"><div class="card-title"><h3>Browsers</h3></div><div id="browsers"></div></article></div></section>
<section id="page-analytics-health" class="page"><div class="page-head"><div><p class="eyebrow">Data operations</p><h1>Analytics health</h1><p>Provider freshness, enrichment coverage, rate denominators and migration status.</p></div></div><div id="providerHealth" class="card card-flush"></div><div class="section"><div class="section-head"><h2>Data quality</h2><p>Unknown values remain visible; historical data is never fabricated.</p></div><div class="card"><div id="quality" class="retention"></div></div></div><div class="section"><div class="section-head"><h2>Rate contracts</h2><p>Raw numerators and denominators; small samples are labelled.</p></div><div id="rateContracts" class="card card-flush"></div></div></section>
<section id="page-product" class="page"><div class="page-head"><div><p class="eyebrow">Product intelligence</p><h1>Builder & predictions</h1><p>Usage and betting performance remain separate, so availability never masquerades as accuracy.</p></div></div><div id="builderKpis" class="grid kpis"></div><div class="grid two section"><article class="card"><div class="card-title"><h3>Builder target odds</h3></div><div id="targets"></div></article><article class="card card-flush"><div class="card-title"><h3>Feature usage</h3></div><div id="features"></div></article></div><div class="section"><div class="section-head"><h2>Prediction performance</h2><p>Settled record and level-stake ROI</p></div><div id="performance" class="card card-flush"></div></div></section>
<section id="page-sporty" class="page"><div class="page-head"><div><p class="eyebrow">Booking operations</p><h1>SportyBet health</h1><p>Code creation, validation, recovery and failure diagnosis.</p></div></div><div class="section-head"><h2>System booking health</h2><p>Automated pipeline activity</p></div><div id="sportyKpis" class="grid kpis"></div><div class="section"><div class="section-head"><h2>User booking engagement</h2><p>Human views and actions; copies are not bets placed.</p></div><div id="userBooking" class="grid kpis"></div></div><div class="grid three section"><article class="card"><div class="card-title"><h3>Catalogue health</h3></div><div id="catalogue"></div></article><article class="card span-2 card-flush"><div class="card-title"><h3>Booking by tier</h3></div><div id="tierBooking"></div></article></div><div class="section"><div class="section-head"><h2>Failure reasons</h2><p>Code copied is never treated as bet placed.</p></div><div id="failures" class="card card-flush"></div></div></section>
<section id="page-content" class="page"><div class="page-head"><div><p class="eyebrow">Growth engine</p><h1>Content</h1><p>Review and publish campaign assets.</p></div><button class="btn" data-act="retry">Retry failed</button></div><div class="section"><div class="section-head"><h2>Homepage event campaign</h2><p>Only visible within a reviewed WAT date range. Otherwise BetSightly automatically highlights upcoming fixtures.</p></div>
<div class="card">
<div class="grid two">
<label>Eyebrow<input id="campaign_eyebrow" class="field" maxlength="50" placeholder="UEFA Champions League"></label>
<label>Headline<input id="campaign_headline" class="field" maxlength="85" placeholder="Champions League week"></label>
<label>Description<input id="campaign_description" class="field" maxlength="220" placeholder="Upcoming fixture coverage, with only verified predictions published."></label>
<label>Official evidence URL<input id="campaign_source_url" class="field" type="url" maxlength="350" placeholder="https://www.uefa.com/..."></label>
<label>Starts (WAT)<input id="campaign_starts_on" class="field" type="date"></label>
<label>Ends (WAT)<input id="campaign_ends_on" class="field" type="date"></label>
<label>Button label<input id="campaign_cta_text" class="field" maxlength="36" placeholder="See predictions"></label>
<label>Button destination<select id="campaign_cta_path" class="field"><option value="/predictions">Predictions</option><option value="/build-slip">Build Slip</option><option value="/results">Results</option><option value="/rollover">Rollover</option></select></label>
</div>
<div class="row wrap" style="margin:15px 0;gap:18px">
<label><input id="campaign_reviewed" type="checkbox"> I verified the event and dates against the evidence URL</label>
<label><input id="campaign_enabled" type="checkbox"> Enable date-limited campaign</label>
</div>
<button class="btn btn-primary" data-act="save-home-campaign">Save homepage campaign</button>
<p id="homeCampaignStatus" class="muted" role="status">Loading campaign settings…</p></div></div>
<div class="note">Social betting content remains approval-first where platform policy requires manual publishing.</div><div class="row wrap section"><select id="fPlatform" class="field" data-change="content"><option value="">All platforms</option></select><select id="fStatus" class="field" data-change="content"><option value="">All statuses</option><option>DRAFT</option><option>APPROVED</option><option>PUBLISHED</option><option>FAILED</option></select></div><div id="contentTable" class="card card-flush section"></div><div id="preview" class="card hidden section"><pre id="previewBody"></pre></div></section>
<section id="page-publishing" class="page"><div class="page-head"><div><p class="eyebrow">Distribution</p><h1>Publishing history</h1><p>Delivery state across every configured channel.</p></div><button class="btn" data-act="retry">Retry failures</button></div><div id="pubTable" class="card card-flush"></div></section>
<section id="page-manual" class="page">
<div class="page-head"><div><p class="eyebrow">Prediction publishing</p><h1>Manual SportyBet desk</h1><p>Publish verified manual selections to an empty tier, or explicitly replace the public Over Goals card while keeping the original engine result intact.</p></div></div>
<div class="note">Use SportyBet event IDs and canonical market codes, one per line. The Over Goals tier accepts only normal over_1_5, over_2_5, over_3_5 or over_4_5 (mixed lines allowed), provided exact live markets exist. Example: 52587,home_win or 17187,over_2_5. The live bookmaker board supplies prices and verifies the full share code before anything goes public. Automated tickets and the official performance record cannot be overwritten.</div>
<div class="manual-workflow" id="manualWorkflow" data-state="idle" aria-live="polite" aria-atomic="true" aria-busy="false" role="status">
 <div class="manual-workflow-head">
  <span class="manual-workflow-icon" id="manualWorkflowIcon" aria-hidden="true">◎</span>
  <div class="manual-workflow-copy">
   <strong class="manual-workflow-title" id="manualWorkflowTitle">Ready to import</strong>
   <span class="manual-workflow-detail" id="manualWorkflowDetail">Select a tier, paste a SportyBet code or add event ID / market rows. Nothing is published until you confirm the reviewed slip.</span>
  </div>
 </div>
 <ol class="manual-workflow-steps" aria-label="Manual publishing progress">
  <li data-manual-step="1">Read code</li>
  <li data-manual-step="2">Review selections</li>
  <li data-manual-step="3">Check live prices</li>
  <li data-manual-step="4">Publish</li>
  <li data-manual-step="5">Confirm saved</li>
 </ol>
 <div class="manual-workflow-help">
  <button type="button" class="btn" data-act="manual-refresh" id="manualRefresh">Refresh published tickets</button>
  <span class="muted">Processing feedback comes from actual server responses. Do not submit again after a network interruption until the saved tickets are checked.</span>
 </div>
</div>
<div class="card section" id="manualEditor">
<div class="row wrap" style="margin-bottom:12px"><label for="manualTier">Destination tier</label><select id="manualTier" class="field"><option value="banker">Banker</option><option value="2_odds">2 Odds (at least 2.00x)</option><option value="5_odds">5 Odds (at least 5.00x)</option><option value="10_odds">10 Odds (at least 10.00x, max 20 legs)</option><option value="over_1_5">Over Goals · mixed overs accumulator</option><option value="rollover">Rollover · 2.00x–4.00x (next eligible day)</option></select></div>
<div id="manualRolloverStatus" class="note hidden" role="status" style="margin-bottom:12px">Rollover eligibility loads with this page. An earlier unsettled day cannot be bypassed.</div>
<label style="display:flex;gap:10px;align-items:flex-start;margin:12px 0" class="hidden"><input type="checkbox" id="manualReplaceOfficialDisplay" style="margin-top:4px"><span><strong>Replace today's displayed official tier with my verified manual ticket</strong><small style="display:block;color:var(--muted)">Available for 2 Odds, 5 Odds, 10 Odds and Over Goals. Original model tickets and codes are preserved for Results and calibration; the new editorial ticket is recorded separately. Cannot overwrite Banker or Rollover.</small></span></label>
<label for="manualShareCode">Import SportyBet booking code</label><div class="row wrap" style="margin:8px 0 14px"><input id="manualShareCode" class="field" placeholder="Paste booking code" autocomplete="off"><button class="btn btn-primary" data-act="manual-import-code">Find games from code</button></div><p class="muted">A fresh standard-market booking code is generated and verified before publication. Features in the original code are not automatically preserved.</p><label for="manualConvertSpecial" class="row wrap" style="gap:10px;margin:8px 0 14px"><input type="checkbox" id="manualConvertSpecial" style="width:19px;height:19px;flex:none"><span><strong>Convert 1UP / 2UP / EarlyGoals to regular markets</strong><small style="display:block;color:var(--muted)">Optional and changes the wager: early-win benefits, Flexi, bonuses and other betslip options are NOT copied. Exact original market odds may change. You must review the new code.</small></span></label><label for="manualLines">SportyBet event ID,market (one per line)</label>
<textarea id="manualLines" class="field" rows="10" style="display:block;width:100%;font-family:var(--mono);resize:vertical;margin:8px 0 10px" placeholder="52587,home_win&#10;17187,over_1_5"></textarea>
<div class="row wrap"><label class="btn">Import CSV <input id="manualFile" type="file" accept=".csv,.txt,text/csv,text/plain" style="display:none"></label><button class="btn" data-act="manual-preview">Check prices / preview</button><button class="btn btn-primary" data-act="manual-publish-imported" id="manualCodePublish" disabled>Publish verified imported code</button><button class="btn" data-act="manual-publish">Publish reviewed rows</button></div><p class="muted">For an existing SportyBet code: choose the tier, enter the code, click <strong>Find games from code</strong>, review every market, then <strong>Check prices / preview</strong>. Only then can you publish. A verified new booking code may differ from your original code.</p>
<p id="manualErr" class="error" role="alert"></p><div id="manualPreview" class="section"></div></div>
<div class="section"><div class="section-head manual-published-head"><div><h2>Today's editorial tickets</h2><p>Bookmaker-validated tickets only; kept separate from automated model history.</p></div></div><div id="manualPublished" class="card card-flush" aria-live="polite"><div class="empty">Loading saved tickets…</div></div></div>
</section>
<section id="page-referrals" class="page"><div class="page-head"><div><p class="eyebrow">Acquisition</p><h1>Referral links</h1></div></div><div class="card"><div class="row wrap"><input id="refCode" class="field" placeholder="Referral code"><input id="refName" class="field" placeholder="Partner name"><button class="btn btn-primary" data-act="add-ref">Create link</button></div><p id="refErr" class="error"></p></div><div id="refTable" class="card card-flush section"></div></section>
<section id="page-settings" class="page"><div class="page-head"><div><p class="eyebrow">Configuration</p><h1>Growth settings</h1></div><button class="btn btn-primary" data-act="save-settings">Save changes</button></div><div class="grid two"><article class="card"><div class="card-title"><h3>Engine</h3></div><div id="engineToggle"></div></article><article class="card"><div class="card-title"><h3>Channels</h3></div><div id="channelToggles"></div></article><article class="card"><div class="card-title"><h3>Auto-publish</h3></div><div id="autoToggles"></div></article><article class="card"><div class="card-title"><h3>Schedule · UTC</h3></div><div id="scheduleFields"></div></article></div><p id="settingsMsg" class="muted"></p></section>
</main></div></div><script src="/admin/app.js"></script></body></html>"""
