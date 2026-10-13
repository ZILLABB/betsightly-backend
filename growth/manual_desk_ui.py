"""Protected same-origin admin HTML page for manual football editorial slips."""

HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BetSightly · Manual Prediction Desk</title>
<style>
:root{color-scheme:dark;--bg:#07110e;--card:#102019;--edge:#294436;--ink:#f3f9f4;--muted:#a2b9ac;--green:#28d581;--amber:#efbd60}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font:15px/1.6 system-ui,Arial,sans-serif;color:var(--ink)}main{max-width:990px;padding:28px 20px 80px;margin:auto}
h1{font-size:clamp(24px,4vw,34px);margin:10px 0}h2{font-size:20px;margin:0 0 16px}a{color:var(--green)}p{color:var(--muted)}.panel{border:1px solid var(--edge);border-radius:15px;padding:22px;margin:18px 0;background:var(--card)}
label{display:block;font-weight:600;margin:10px 0 6px}input,select,textarea{width:100%;padding:12px;color:var(--ink);background:#142920;border:1px solid #365b46;border-radius:10px;font:inherit}
textarea{min-height:175px;font-family:ui-monospace,Consolas,monospace;font-size:13px;resize:vertical}button{font:inherit;background:var(--green);border:0;color:#062112;font-weight:700;border-radius:10px;padding:12px 16px;cursor:pointer;min-height:45px}
button:disabled{opacity:.5;cursor:wait}button.secondary{background:#233c30;color:var(--ink);border:1px solid #3f664e}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
.badge{display:inline-block;background:#243d30;color:var(--green);border-radius:20px;padding:3px 10px;font-size:12px}.warn{padding:13px 16px;border-left:3px solid var(--amber);background:#332718;color:#eedcbb;margin:15px 0;border-radius:8px}.hint{font-size:13px;color:var(--muted)}
#result{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;background:#081711;border:1px solid var(--edge);padding:16px;border-radius:10px;max-height:360px;overflow:auto;font:12px/1.5 ui-monospace,Consolas,monospace}
#result.error{border-color:#b75353;color:#ffa9a9}.row{display:grid;grid-template-columns:1fr 1fr;gap:15px}@media(max-width:660px){.row{grid-template-columns:1fr}.panel{padding:16px}}
</style></head><body><main>
<a href="/admin">← BetSightly Command Center</a>
<h1>Manual Prediction Desk <span class="badge">Admin only</span></h1>
<p>Fill gaps in today's football coverage with your own reviewed markets. Preview before publishing. This does not replace the model's historical official predictions.</p>
<div class="warn"><strong>Two different publication modes:</strong> Editorial research displays a manually chosen opinion without a bookmaker code. Verify + publish submits the selected full slip to SportyBet and displays a booking link <strong>only after full readback succeeds</strong>. Manual selections do not inherit a model confidence or profitability guarantee.</div>
<section class="panel">
<h2>Today's manual selections</h2>
<div class="row"><div><label for="tier">Choose tier</label>
<select id="tier"><option value="banker">Banker (one game)</option><option value="2_odds">2 Odds (≥2.00x)</option><option value="5_odds">5 Odds (≥5.00x)</option><option value="10_odds">10 Odds (≥10.00x; max 20 games)</option><option value="over_1_5">Over 1.5 goals</option></select>
</div><div><label for="file">Upload CSV (optional)</label><input id="file" type="file" accept=".csv,text/csv,.txt"></div></div>
<label for="legs">One selection per line (pipe or comma separated)</label>
<p class="hint">Columns: <code>SportyBet match ID | Home team | Away team | League | Kickoff ISO with time zone | Market key</code>. Kickoff must be in the future, at least 20 minutes away, and fall on today's Lagos date. Example:</p>
<div class="hint">52587 | Arsenal | Lille | UEFA Champions League | 2026-10-13T20:00:00+01:00 | home_win</div>
<p class="hint">The example is for formatting only: verify the actual kickoff and market before publishing. Supported keys include home_win, away_win, home_or_draw, away_or_draw, over_1_5, over_2_5 and btts_yes.</p>
<textarea id="legs" placeholder="SportyBet ID | Home | Away | League | YYYY-MM-DDTHH:mm:ss+01:00 | market"></textarea>
<label for="note">Editor's note (optional)</label>
<textarea id="note" style="min-height:68px" placeholder="Why these games? Injuries, form, risk context..."></textarea>
<div class="actions"><button class="secondary" id="preview">Preview and validate</button>
<button class="secondary" id="research">Publish as research only</button>
<button id="book">Verify live SportyBet code + publish</button></div>
<p class="hint">Once a tier is published today it cannot silently be replaced. If SportyBet validation fails, nothing is published. Existing Rollover and other published fixtures cannot be repeated.</p>
</section>
<section class="panel"><h2>Validation and booking result</h2><div id="result" role="status" aria-live="polite">No submission yet.</div></section>
<section class="panel"><h2>Today's published editorial picks</h2><div id="published" role="status">Loading…</div></section>
</main>
<script>
'use strict';
const $=id=>document.getElementById(id);
function parseLines(raw){
 return raw.split(/\r?\n/).map(s=>s.trim()).filter(s=>s&&!s.startsWith('#')).map((s,i)=>{
  const cells=s.includes('|')?s.split('|'):s.split(',');
  if(cells.length!==6)throw Error('Line '+(i+1)+' needs exactly six columns');
  const [sportybet_event_id,home_team,away_team,league,kickoff,market]=cells.map(c=>c.trim().replace(/^"|"$/g,''));
  return {sportybet_event_id,home_team,away_team,league,kickoff,market};
 });
}
function form(){
 return {tier:$('tier').value,legs:parseLines($('legs').value),note:$('note').value};
}
function show(obj,bad=false){
 $('result').className=bad?'error':'';
 $('result').textContent=typeof obj==='string'?obj:JSON.stringify(obj,null,2);
}
async function submit(mode){
 const btns=[$('preview'),$('research'),$('book')];
 btns.forEach(b=>b.disabled=true);
 try{
  const payload={...form(),mode};
  if(!payload.legs.length)throw Error('Enter or upload at least one game');
  if(mode!=='preview'&&!confirm('Publish '+payload.legs.length+' manually curated selections in '+payload.tier+'? This cannot overwrite earlier publications.'))return;
  const uri='/api/growth/manual-desk/'+(mode==='preview'?'preview':'publish');
  const response=await fetch(uri,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await response.json();
  if(!response.ok)throw Error(data.detail||'Request failed (HTTP '+response.status+')');
  show(data);if(mode!=='preview')await loadPublished();
 }catch(err){show(err.message||'Unable to submit.',true);}
 finally{btns.forEach(b=>b.disabled=false);}
}
async function loadPublished(){
 try{
  const r=await fetch('/api/growth/editorial-slips');
  const v=await r.json();
  const container=$('published');container.replaceChildren();
  if(!v.slips?.length){container.textContent='No manual predictions published today.';return;}
  v.slips.forEach(s=>{
   const block=document.createElement('div');block.style.marginBottom='16px';
   const title=document.createElement('strong');title.textContent=s.tier.replaceAll('_',' ')+' · '+(s.status==='BOOKED'?'Full booking verified':'Research only');
   block.append(title);
   (s.legs||[]).forEach(g=>{const p=document.createElement('p');p.textContent=g.home_team+' vs '+g.away_team+' · '+g.market;block.append(p)});
   if(s.booking?.actionable&&s.booking?.share_url){
    const a=document.createElement('a');a.href=s.booking.share_url;a.textContent='Open verified SportyBet booking';a.rel='noopener noreferrer';a.target='_blank';block.append(a);
   } container.append(block);
  });
 }catch(e){$('published').textContent='Unable to load editorial picks.';}
}
$('preview').addEventListener('click',()=>submit('preview'));
$('research').addEventListener('click',()=>submit('research'));
$('book').addEventListener('click',()=>submit('book'));
$('file').addEventListener('change',async e=>{
 const file=e.target.files?.[0];if(file)$('legs').value=await file.text();
});
loadPublished();
</script></body></html>"""
