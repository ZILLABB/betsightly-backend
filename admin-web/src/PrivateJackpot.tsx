import {useRef, useState} from 'react';
import {AlertTriangle, CheckCircle2, Clipboard, Loader2, RefreshCcw, ShieldCheck, Sparkles, Target} from 'lucide-react';
import {api} from './api';
import MarketExplorer from './MarketExplorer';

type Candidate = {selection_id:string;match_id:string;home_team?:string;away_team?:string;league?:string;
  kickoff?:string;market:string;odds:number;trust_grade?:string;selection_probability?:number};
type Board = {status:string;reason?:string;candidate_count?:number;distinct_fixture_count?:number;
  maximum_reference_odds?:number;maximum_legs_available?:number;upper_bound_explanation?:string;
  available_leagues?:string[];candidates?:Candidate[]};
type Proposal = {status:string;reason?:string;selection_ids?:string[];selected_games?:Candidate[];legs?:number;
  indicative_odds?:number;target_odds?:number;maximum_reference_odds?:number;
  estimated_conservative_hit_probability?:number;fixtures_evaluated?:number;
  estimated_all_leg_probability?:number;candidate_count?:number;distinct_fixture_count?:number;
  maximum_model_eligible_reference_odds?:number;fixtures_without_valid_probability?:number;portfolio_type?:string;full_ticket_complete?:boolean;partial_reference_odds?:number|null;};
type PasteMatch = {line:number;home_team:string;away_team:string;matched_home?:string;matched_away?:string;requested_market?:string|null;reason?:string;suggested_match?:string};
type PasteReport = Proposal & {pasted_fixture_count?:number;matched_fixture_count?:number;unmatched_fixture_count?:number;matched?:PasteMatch[];unmatched?:PasteMatch[];note?:string;exact_market_mode?:boolean;requested_market_count?:number;full_ticket_complete?:boolean;partial_reference_odds?:number|null;board_complete?:boolean};
type Booking = Proposal & {share_code?:string;share_url?:string;verified_odds?:number;
  readback_status?:string;expires_at?:string;priced_at?:string;
  publication_status?:string;proposal?:Proposal;invalid_selections?:any[]};
const decimal=(value:number,max=2)=>Number.isFinite(value)?value.toLocaleString('en-NG',{maximumFractionDigits:max}):'—';
const friendly=(value:unknown)=>value instanceof Error?value.message:'Unexpected request error';
const suggestedTargets=[2,5,10,100,1000,10000,100000];

export default function PrivateJackpot() {
 const [horizon,setHorizon]=useState('7_days');
 const [mode,setMode]=useState<'approved_model'|'bookmaker_only'>('approved_model');
 const [confirmReady,setConfirmReady]=useState(false);
 const [grade,setGrade]=useState('B');
 const [style,setStyle]=useState('all');
 const [legFloor,setLegFloor]=useState('1.01');
 const [legLimit,setLegLimit]=useState('50');
 const [target,setTarget]=useState('100000');
 const [board,setBoard]=useState<Board|null>(null);
 const [proposal,setProposal]=useState<Proposal|null>(null);
 const [pasteText,setPasteText]=useState('');
 const [pasteReport,setPasteReport]=useState<PasteReport|null>(null);
 const [booking,setBooking]=useState<Booking|null>(null);
 const [busy,setBusy]=useState<'board'|'analyze'|'book'|null>(null);
 const [message,setMessage]=useState('');
 const [expand,setExpand]=useState(false);
 const busyLatch=useRef(false);
 const amount=Number(target);
 const maxLegs=Number(legLimit);
 const bookmakerOnly=mode==='bookmaker_only';
 const modeReady=!bookmakerOnly||Boolean(pasteText.trim());
 const invalidPreview=Boolean(pasteText.trim()&&pasteReport&&pasteReport.status!=='PROPOSED_NOT_BOOKED');
 const targetValid=Number.isFinite(amount)&&amount>=2&&amount<=100000;
 const preferences=()=>({horizon:bookmakerOnly?'today':horizon,selection_mode:mode,min_trust_grade:grade,min_probability:.65,market_style:style,
   min_leg_odds:Number(legFloor),markets:[],target_odds:amount,max_legs:maxLegs});
 const changed=()=>{setBoard(null);setProposal(null);setBooking(null);setPasteReport(null);setConfirmReady(false);setMessage('')};
 const inspect=async()=>{
  if(busyLatch.current)return;
  busyLatch.current=true;setBusy('board');setMessage('');setBooking(null);setProposal(null);
  try {
   const result=await api<Board>('private-jackpot/candidates',preferences(),'POST');
   setBoard(result);
   if(result.status!=='success')setMessage(result.reason||'Approved match board not ready.');
  }catch(e){setBoard(null);setMessage(friendly(e))}
  finally{setBusy(null);busyLatch.current=false}
 };
 const analyze=async()=>{
  if(busyLatch.current||!targetValid||!modeReady)return;
  setConfirmReady(false);
  busyLatch.current=true;setBusy('analyze');setMessage('');setBooking(null);setProposal(null);setPasteReport(null);
  try {
   const pasted=pasteText.trim().length>0;
   const result=await api<PasteReport>(pasted?'private-jackpot/paste-preview':'private-jackpot/optimize',
     pasted?{...preferences(),fixtures_text:pasteText}:preferences(),'POST');
   if(pasted)setPasteReport(result);
   setProposal(result);
   if(result.status!=='PROPOSED_NOT_BOOKED')setMessage(result.reason||'No eligible ticket for this target.');
  }catch(e){setMessage(friendly(e))}
  finally{setBusy(null);busyLatch.current=false}
 };
 const generate=async()=>{
  if(busyLatch.current||!targetValid||!modeReady||invalidPreview)return;
  // Inline confirmation does not block the browser event handler.
  if(!confirmReady){setConfirmReady(true);return;}
  setConfirmReady(false);
  busyLatch.current=true;setBusy('book');setMessage('');setBooking(null);setProposal(null);setPasteReport(null);
  try {
   const pasted=pasteText.trim().length>0;
   const result=await api<Booking & {pasted_preview?:PasteReport}>(
    pasted?'private-jackpot/paste-book':'private-jackpot/auto-book',
    pasted?{...preferences(),fixtures_text:pasteText}:preferences(),'POST'
   );
   if(result.pasted_preview)setPasteReport(result.pasted_preview);
   else if(pasted)setPasteReport(result as PasteReport);
   setBooking(result);
   if(result.proposal)setProposal(result.proposal);
   else if(result.pasted_preview)setProposal(result.pasted_preview);
   else if(result.maximum_reference_odds!==undefined)setProposal(result);
   if(result.status!=='success'||!result.share_code||result.readback_status!=='PASSED')
    setMessage(result.reason||'No exact SportyBet booking code could be validated.');
  }catch(e){setMessage(friendly(e)+'. If the request timed out, do not automatically repeat it; check code records first.')}
  finally{setBusy(null);busyLatch.current=false}
 };
 const displayed=booking?.proposal||proposal;
 const selectedIds=booking?.selection_ids||displayed?.selection_ids||[];
 const candidates=board?.candidates||[];
 const selectedGames=displayed?.selected_games||selectedIds.map(key=>candidates.find(c=>c.selection_id===key)).filter((x):x is Candidate=>Boolean(x));
 const optimisticCeiling=board?.maximum_reference_odds;
 const partial=Boolean(pasteReport&&pasteReport.full_ticket_complete===false);
 const currentCeiling=partial?undefined:(displayed?.maximum_reference_odds??optimisticCeiling);
 const modelCeiling=bookmakerOnly?undefined:displayed?.maximum_model_eligible_reference_odds;
 const impossible=Number.isFinite(currentCeiling)&&Number(currentCeiling)<amount;
 const modelInsufficient=Number.isFinite(modelCeiling)&&Number(modelCeiling)<amount;
 const experimental=displayed?.portfolio_type==='HIGH_RISK_CEILING_EXPERIMENT';
 const trustworthy=(booking?.status==='success'&&booking.share_code&&booking.readback_status==='PASSED');
 return <>
  <div className="page-heading"><div><span className="eyebrow">PRIVATE · AUTOMATIC · SPORTYBET VERIFIED</span>
   <h1>Smart Jackpot Generator.</h1>
   <p>One click searches the available BetSightly-approved matches and creates a verified share code when your odds target is achievable. You do not need to pick matches.</p>
  </div></div>
  <section className="panel">
   <header className="panel-head"><div><h2>Automatic ticket settings</h2>
    <p>Use only model-evaluated, bookmaker-bookable fixtures. Research and booking remain separate from public predictions.</p></div><ShieldCheck size={21}/></header>
   <fieldset className="editor" disabled={busy!==null}>
    <label className="jackpot-policy-control">Private selection policy
     <select value={mode} onChange={e=>{setMode(e.target.value as 'approved_model'|'bookmaker_only');changed()}}>
      <option value="approved_model">Model-approved · confidence and bookmaker gates</option>
      <option value="bookmaker_only">Bookmaker-only experiment · relaxed model gates</option>
     </select>
    </label>
    {bookmakerOnly&&<div className="notice warning"><AlertTriangle size={17}/><div>
     Private, today-only experimental mode. Paste an exact market for every game.
     Selection confidence and trust grades are not enforced, but exact SportyBet
     fixtures, active prices and full-code readback still are. No Under markets or stakes.
    </div></div>}
    <div className="jackpot-controls">
     <label>Search window
      <select value={bookmakerOnly?"today":horizon} disabled={bookmakerOnly} onChange={e=>{setHorizon(e.target.value);changed()}}>
       <option value="today">Today only</option>
       <option value="3_days">Next 3 days</option>
       <option value="7_days">Next 7 days · more fixtures</option>
      </select></label>
     <label>Evidence/trust level
      <select value={grade} disabled={bookmakerOnly} onChange={e=>{setGrade(e.target.value);changed()}}>
       <option value="A">A only · strict</option>
       <option value="B">A + B · balanced</option>
       <option value="C">A + B + C · exploratory / higher uncertainty</option>
      </select></label>
     <label>Market strategy
      <select value={style} disabled={bookmakerOnly} onChange={e=>{setStyle(e.target.value);changed()}}>
       <option value="all">All approved (no Under markets)</option>
       <option value="goals">Overs + BTTS</option>
       <option value="results">1X2 + double chance + DNB</option>
       <option value="wins">Straight wins only</option>
      </select></label>
     <label>Max games per ticket
      <select value={legLimit} onChange={e=>{setLegLimit(e.target.value);changed()}}>
       <option value="10">10 matches</option><option value="20">20 matches</option>
       <option value="30">30 matches</option><option value="40">40 matches</option>
       <option value="50">50 matches</option>
      </select></label>
     <label>Minimum odds per match
      <select value={legFloor} onChange={e=>{setLegFloor(e.target.value);changed()}}>
       <option value="1.01">No extra odds restriction</option>
       <option value="1.20">1.20x or higher</option>
       <option value="1.40">1.40x or higher</option>
       <option value="1.60">1.60x or higher</option>
       <option value="1.80">1.80x or higher</option>
      </select></label>
     <label>Target accumulator odds
      <input type="number" value={target} min={2} max={100000} step="any"
       onChange={e=>{setTarget(e.target.value);changed()}}/></label>
    </div>
    <div className="jackpot-paste-section">
      <label htmlFor="private-jackpot-paste"><strong>Paste today's fixtures and exact picks (optional)</strong></label>
      <p className="muted">Use <code>Home vs Away | Home win @1.65</code> or <code>Home vs Away | BTTS Yes @1.53</code>. If you supply picks, supply one on every line; the system keeps the exact markets instead of replacing them. Without picks, markets are selected automatically. Pasted @prices are never trusted.</p>
      <textarea id="private-jackpot-paste" rows={7} value={pasteText}
       placeholder={'Dinamo Zagreb vs NEC Nijmegen | Home win @1.71\nBraga vs Gent | Home win @1.81\nAjax vs Atalanta | BTTS Yes @1.63'}
       onChange={e=>{setPasteText(e.target.value);changed()}} maxLength={9000}/>
      {pasteText.trim()&&<button className="mini-button" type="button" onClick={()=>{setPasteText('');changed()}}>Clear fixture list · use full BetSightly pool</button>}
    </div>
    <div className="jackpot-presets" aria-label="Quick odds targets">
     {suggestedTargets.map(value=><button key={value} type="button" className={'mini-button '+(amount===value?'jackpot-preset-active':'')} onClick={()=>{setTarget(String(value));changed()}}>{decimal(value,0)}x</button>)}
    </div>
    <div className="toolbar">
     <button className="button primary" type="button" disabled={!targetValid||!modeReady||invalidPreview||busy!==null} onClick={generate}>
      {busy==='book'?<Loader2 size={17} className="spin"/>:<Sparkles size={17}/>}
      {busy==='book'?'Verifying exact bookmaker code…':confirmReady?'Confirm private code generation':'Auto-generate verified SportyBet code'}
     </button>
     <button type="button" className="button secondary" disabled={!targetValid||!modeReady||busy!==null} onClick={analyze}>
      {busy==='analyze'?<Loader2 size={17} className="spin"/>:<Target size={17}/>}
      {busy==='analyze'?'Checking prices and fixtures…':bookmakerOnly?'Preview bookmaker-only exact picks':'Preview best automatic combination'}
     </button>
     <button type="button" className="mini-button" disabled={busy!==null} onClick={inspect}>
      {busy==='board'?<Loader2 size={16} className="spin"/>:<RefreshCcw size={16}/>} Check available games
     </button>
    </div>
   </fieldset>
   <div className="notice info"><ShieldCheck size={17}/><div>Never forces legs to hit a target, never includes Under-goals markets and never places a stake. A 100,000x ticket is extremely unlikely to win. The approved match universe is currently limited to a 7-day prepared board; more future dates require additional provider coverage.</div></div>
   {!bookmakerOnly&&grade==='C'&&<div className="notice warning"><AlertTriangle size={17}/><div>Exploratory trust C includes less-supported predictions, not more reliable ones. The minimum model-probability and bookability gates still apply.</div></div>}
   {pasteReport&&<div className="jackpot-paste-results" role="status">
    <strong>Fixture matching: {pasteReport.matched_fixture_count||0} accepted / {pasteReport.pasted_fixture_count||0} pasted{pasteReport.exact_market_mode?' · Exact picks preserved':' · Picks auto-selected'}</strong>
    {(pasteReport.unmatched_fixture_count||0)>0&&<>
     <div className="notice warning"><AlertTriangle size={17}/><div>{pasteReport.unmatched_fixture_count} pasted fixtures or exact markets are unavailable in this mode. No missing pick will be substituted.</div></div>
     <div className="jackpot-ticket-list">{(pasteReport.unmatched||[]).map(item=>
      <div className="jackpot-ticket-item" key={item.line}>
       <span>{item.line}. {item.home_team} vs {item.away_team}{item.requested_market?' | '+item.requested_market.replaceAll('_',' '):''}
       <small>{item.reason?.replaceAll('_',' ')}{(item as PasteMatch & {detail?:string}).detail?' · '+(item as PasteMatch & {detail?:string}).detail:''} {item.suggested_match?' · Possible name: '+item.suggested_match:''}</small></span>
      </div>)}</div>
    </>}
   </div>}
   {message&&<div className="notice warning" role="alert"><AlertTriangle size={17}/><div>{message}</div></div>}
  </section>
  <MarketExplorer preferences={preferences}/>
  {(board?.status==='success'||displayed)&&<section className="panel">
   <header className="panel-head"><div><h2>Feasibility & match coverage</h2><p>Shows available fixtures, not duplicate markets counted as matches.</p></div></header>
   <div className="jackpot-feasibility">
    <div><small>Approved markets</small><strong>{decimal(board?.candidate_count??displayed?.candidate_count??0,0)}</strong></div>
    <div><small>Distinct fixtures</small><strong>{decimal(board?.distinct_fixture_count??displayed?.distinct_fixture_count??0,0)}</strong></div>
    <div><small>Raw price ceiling</small><strong>{currentCeiling==null?'—':decimal(Number(currentCeiling))+'x'}</strong></div>
    {modelCeiling!=null&&<div><small>Model-eligible ceiling</small><strong>{decimal(Number(modelCeiling))}x</strong></div>}
    <div><small>Required target</small><strong>{decimal(amount)}x</strong></div>
    <p>{impossible
     ?'NOT POSSIBLE FROM CURRENT PRICES: even taking the highest listed market from each fixture cannot reach this target.'
     :modelInsufficient
     ?'INSUFFICIENT MODEL EVIDENCE: prices appear to reach the target, but some selections do not have valid model reliability. No qualified ticket is available.'
     :'Reference odds alone do not guarantee bookmaker acceptance or good predictions. Model-eligible odds are assessed separately.'}</p>
   </div>
   {board?.available_leagues?.length?<>
    <button className="mini-button" type="button" onClick={()=>setExpand(x=>!x)} aria-expanded={expand}>{expand?'Hide':'Show'} {board.available_leagues.length} competitions and fixture options</button>
    {expand&&<><p className="muted">{board.available_leagues.join(' · ')}</p>
     <div className="jackpot-ticket-list">{candidates.slice(0,100).map(item=><div className="jackpot-ticket-item" key={item.selection_id}>
      <span>{item.home_team} vs {item.away_team}<small>{item.league||'Football'} · {item.market.replaceAll('_',' ')} · {item.trust_grade||'—'} trust</small></span>
      <strong>{decimal(item.odds)}x</strong></div>)}</div>
     {candidates.length>100&&<p className="muted">Showing 100 of {candidates.length} approved market options.</p>}
    </>}
   </>:null}
  </section>}
  {displayed?.status==='PROPOSED_NOT_BOOKED'&&<section className="panel">
   <header className="panel-head"><div><h2>Automatic selection proposal</h2>
    <p>{displayed.legs} distinct fixtures · estimated reference odds {decimal(Number(displayed.indicative_odds||0))}x · no booking code yet.</p></div><CheckCircle2 size={20}/></header>
   <div className={experimental?'notice warning':'notice info'}>
     {experimental?<AlertTriangle size={17}/>:<Target size={17}/>}
     <div>{experimental
      ?'HIGH-RISK CEILING EXPERIMENT: the normal probability search did not find a qualifying ticket. This fallback takes the highest-priced model-eligible market from each chosen match, not the most reliable combination. It is not a recommendation.'
      :'This is a bounded confidence-first model proposal, not a guaranteed optimum.'} No bookmaker code exists until verification succeeds.</div>
   </div>
   {selectedGames.length>0&&<div className="jackpot-ticket-list">{selectedGames.map((game,i)=><div className="jackpot-ticket-item" key={game.selection_id}><span>{i+1}. {game.home_team} vs {game.away_team}<small>{game.market.replaceAll('_',' ')} · {game.trust_grade||'—'} trust</small></span><strong>{decimal(game.odds)}x</strong></div>)}</div>}
   {selectedGames.length===0&&<p className="muted">To see individual match selections, select “Check available games” after this proposal. You never have to make the selections yourself.</p>}
  </section>}
  {trustworthy&&<section className="panel">
   <header className="panel-head"><div><h2>SportyBet verified booking code</h2><p>Matched exactly through bookmaker readback; no stake or public publication.</p></div><CheckCircle2 size={21}/></header>
   <div className="jackpot-code" role="status"><p><CheckCircle2 size={18}/> {booking?.legs} of {booking?.legs} selections verified</p>
    <strong>{booking?.share_code}</strong>
    <div>Live bookmaker total: {decimal(Number(booking?.verified_odds||0))}x</div>
    <div>Expiry: {booking?.expires_at||'Not provided'}</div>
    <button className="mini-button" onClick={()=>booking?.share_code&&navigator.clipboard.writeText(booking.share_code)} type="button"><Clipboard size={16}/> Copy booking code</button>
    <small>The code may expire or prices may change. Always read it back before acting.</small>
   </div>
  </section>}
 </>;
}
