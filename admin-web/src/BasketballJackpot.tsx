import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Activity, AlertCircle, ArrowRight, Check, CheckCircle2, Clipboard, ClipboardPaste, Clock3, Database, FileCheck2, LayoutGrid, Loader2, RefreshCcw, Search, ShieldCheck, Ticket, Trash2} from 'lucide-react';
import {api} from './api';
import './basketball-jackpot.css';

type Outcome={outcome_id:string;label:string;odds:number};
type Market={market_id:string;specifier:string;label:string;outcomes:Outcome[]};
type Fixture={event_id:string;home_team:string;away_team:string;competition:string;kickoff_ms:number;markets:Market[]};
type Pick={event_id:string;market_id:string;outcome_id:string;specifier:string;label:string;fixture:string;odds:number};
type Board={status:string;reason?:string;fixtures:Fixture[];fetched_at?:number;metadata?:{snapshot_id?:string}};
type Unmatched={line:number;reason:string;detail?:string};
type HistoricalLeg={event_id:string;home_team:string;away_team:string;competition?:string;selection:string;odds:number;
  result?:string;score?:{home:number;away:number}|null;score_source?:string|null;};
type HistoricalTicket={fingerprint:string;share_code?:string|null;status:string;created_at:string;expires_at?:string|null;
  target_odds:number;verified_odds?:number|null;verified_odds_source?:string;legs:HistoricalLeg[];
  leg_count:number;detail?:{ticket_status?:string;reason?:string};last_checked_at?:string|null;};
type HistoryList={status:string;tickets:HistoricalTicket[];count:number;};
type Quote={status:string;reason?:string;indicative_odds?:number;verified_odds?:number;matched_fixture_count?:number;
  pasted_fixture_count?:number;full_ticket_complete?:boolean;share_code?:string|null;readback_status?:string;
  verified_odds_source?:string;
  unmatched?:Unmatched[];share_url?:string;legs?:number};

const errorText=(e:unknown)=>e instanceof Error?e.message:'Unexpected problem contacting the server';
const odds=(n:unknown)=>Number.isFinite(Number(n))?Number(n).toLocaleString('en-NG',{maximumFractionDigits:3}):'—';
const time=(ms:number)=>new Date(ms).toLocaleString('en-NG',{timeZone:'Africa/Lagos',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
const eventTitle=(event:Fixture)=>event.home_team+' vs '+event.away_team;
const major=['NBA','Euroleague','Liga ACB','BBL','LNB Elite','LKL','Serie A','Super Lig','United League'];
const women=(event:Fixture)=>/women|womens|wbl|wnba|feminin|basket liga, women|lfb|dbbl|zbl/i.test(event.competition+' '+event.home_team+' '+event.away_team);
const busyCopy={load:'Loading bookmaker data…',refresh:'Refreshing SportyBet board…',preview:'Matching every selection…',book:'Creating and verifying your code…'};
const samples=['Boston Celtics vs New York Knicks | Home win','Los Angeles Lakers vs Utah Jazz | Over 221.5','Olimpia Milano vs Virtus Bologna | Away win'];


const DRAFT_KEY='betsightly:basketball:unsent-ticket:v1';
type TicketDraft={mode:'paste'|'browse';paste:string;selected:Pick[];target:string;updated_at:number;booking_attempted:boolean};
function loadDraft():TicketDraft|null{
 try{
  const raw=window.sessionStorage.getItem(DRAFT_KEY);
  if(!raw)return null;
  const value:unknown=JSON.parse(raw);
  if(!value||typeof value!=='object')return null;
  const d=value as Partial<TicketDraft>;
  if(!Number.isFinite(Number(d.updated_at))||Date.now()-Number(d.updated_at)>24*60*60*1000)return null;
  if(d.mode!=='paste'&&d.mode!=='browse')return null;
  if(typeof d.paste!=='string'||d.paste.length>9000)return null;
  if(typeof d.target!=='string'||!Number.isFinite(Number(d.target)))return null;
  if(!Array.isArray(d.selected)||d.selected.length>50||
     d.selected.some(p=>!p||typeof p.event_id!=='string'||typeof p.market_id!=='string'||
       typeof p.outcome_id!=='string'||typeof p.specifier!=='string'||
       typeof p.label!=='string'||typeof p.fixture!=='string'||
       !Number.isFinite(p.odds)))return null;
  return d as TicketDraft;
 }catch{return null;}
}

export default function BasketballJackpot(){
 const restored=useRef<TicketDraft|null>(loadDraft());
 const [board,setBoard]=useState<Board|null>(null);
 const [mode,setMode]=useState<'paste'|'browse'>(restored.current?.mode||'paste');
 const [paste,setPaste]=useState(restored.current?.paste||'');
 const [selected,setSelected]=useState<Pick[]>(restored.current?.selected||[]);
 const [search,setSearch]=useState('');
 const [filter,setFilter]=useState('Featured');
 const [limit,setLimit]=useState(14);
 const [target,setTarget]=useState(restored.current?.target||'100');
 const [bookingAttempted,setBookingAttempted]=useState(Boolean(restored.current?.booking_attempted));
 const [quote,setQuote]=useState<Quote|null>(null);
 const [receipt,setReceipt]=useState<Quote|null>(null);
 const [notice,setNotice]=useState('');
 const [busy,setBusy]=useState<'load'|'refresh'|'preview'|'book'|null>(null);
 const [confirm,setConfirm]=useState(false);
 const [historyRows,setHistoryRows]=useState<HistoricalTicket[]>([]);
 const [historyBusy,setHistoryBusy]=useState<'loading'|'settling'|null>(null);
 const [historyError,setHistoryError]=useState('');
 const [historyInfo,setHistoryInfo]=useState('');
 const [recovering,setRecovering]=useState<string|null>(null);
 const lock=useRef(false);
 const load=async()=>{
   if(lock.current)return;
   lock.current=true;setBusy('load');setNotice('');
   try{setBoard(await api<Board>('basketball-jackpot/board'));}
   catch(e){
     setBoard({status:'SERVICE_UNAVAILABLE',fixtures:[],
       reason:'The bookmaker API is temporarily unreachable. This does not mean the stored basketball board is empty.'});
     setNotice(errorText(e));
   }finally{lock.current=false;setBusy(null);}
 };
 const loadHistory=async()=>{
   setHistoryBusy('loading');setHistoryError('');
   try{const saved=await api<HistoryList>('basketball-jackpot/history');if(saved.status!=='success'||!Array.isArray(saved.tickets))throw Error('Booking history response was incomplete.');setHistoryRows(saved.tickets);}
   catch(e){setHistoryError(errorText(e));}
   finally{setHistoryBusy(null);}
 };
 const recoverSaved=async(fingerprint:string)=>{
   if(recovering||historyBusy)return;
   setRecovering(fingerprint);setHistoryError('');setHistoryInfo('');
   try{
     // Bookmaker readback ONLY: the backend derives every leg from the saved
     // fingerprint and cannot send a new share-code creation request.
     const result=await api<Quote>('basketball-jackpot/recover',{fingerprint},'POST');
     const saved=await api<HistoryList>('basketball-jackpot/history');
     setHistoryRows(saved.tickets);
     if(result.status==='success'&&result.readback_status==='PASSED'&&result.share_code){
       setHistoryInfo('Existing code verified and saved at '+odds(result.verified_odds)+'x. No new SportyBet share request was made.');
     }else{
       setHistoryError(result.reason||'The original code could not be verified. It remains hidden; no new share request was made.');
     }
   }catch(e){setHistoryError(errorText(e)+' No new share-code request was made.');}
   finally{setRecovering(null);}
 };
 const settleHistory=async()=>{
   if(historyBusy)return;
   setHistoryBusy('settling');setHistoryError('');
   try{
     const result=await api<{status:string;failures?:string[]}>('basketball-jackpot/settle',{},'POST');
     if(result.status!=='success')setHistoryError('Result source incomplete. Unverified games remain pending.');
     const saved=await api<HistoryList>('basketball-jackpot/history');setHistoryRows(saved.tickets);
   }catch(e){setHistoryError(errorText(e));}
   finally{setHistoryBusy(null);}
 };
 useEffect(()=>{void load();void loadHistory();},[]);
 // Only unsent draft inputs survive a same-tab reload. Never persist a booking
 // code, unverified quote, or approval flag; every reload needs fresh preview.
 useEffect(()=>{
   try{window.sessionStorage.setItem(DRAFT_KEY,JSON.stringify({
     mode,paste,selected,target,booking_attempted:bookingAttempted,updated_at:Date.now()} satisfies TicketDraft));}catch{}
 },[mode,paste,selected,target,bookingAttempted]);
 const reset=()=>{setQuote(null);setReceipt(null);setNotice('');setConfirm(false);};
 const edit=()=>{reset();setBookingAttempted(false);};
 const refresh=async()=>{
   if(lock.current)return;
   lock.current=true;setBusy('refresh');reset();
   try{
     const result=await api<{status:string;reason?:string}>('basketball-jackpot/refresh',{},'POST');
     setBoard(await api<Board>('basketball-jackpot/board'));
     if(result.status!=='success')setNotice(result.reason||'Incomplete provider crawl; last completed snapshot was retained.');
   }catch(e){setNotice(errorText(e));}finally{setBusy(null);lock.current=false;}
 };
 const switchMode=(next:'paste'|'browse')=>{setMode(next);reset();};
 const add=(fixture:Fixture,value:string)=>{
   const [market_id,specifier,outcome_id]=value.split('~');
   const market=fixture.markets.find(m=>m.market_id===market_id&&m.specifier===specifier);
   const outcome=market?.outcomes.find(o=>o.outcome_id===outcome_id);
   if(!outcome||selected.some(p=>p.event_id===fixture.event_id)||selected.length>=50)return;
   setSelected(prev=>[...prev,{event_id:fixture.event_id,market_id,specifier,outcome_id,
     label:outcome.label,odds:outcome.odds,fixture:eventTitle(fixture)}]);
   edit();
 };
 const shown=useMemo(()=>((board?.fixtures||[]).filter(f=>{
   const match=eventTitle(f)+' '+f.competition;
   if(!match.toLowerCase().includes(search.toLowerCase()))return false;
   if(filter==='Women')return women(f);
   if(filter==='All')return true;
   if(filter==='NBA')return f.competition.toUpperCase().includes('NBA');
   return !women(f)&&major.some(x=>f.competition.toLowerCase()===x.toLowerCase());
 })).sort((a,b)=>a.kickoff_ms-b.kickoff_ms),[board,search,filter]);
 const lineCount=paste.split(/\r?\n/).filter(x=>x.trim()).length;
 const legCount=mode==='paste'?lineCount:selected.length;
 const total=selected.reduce((v,p)=>v*p.odds,1);
 const allowedTarget=Number.isFinite(Number(target))&&Number(target)>=2&&Number(target)<=100000;
 const ready=allowedTarget&&legCount>=1&&legCount<=50;
 const complete=quote?.status==='PROPOSED_NOT_BOOKED'&&quote.full_ticket_complete===true;
 const success=receipt?.status==='success'&&!!receipt.share_code&&receipt.readback_status==='PASSED';
 const bookingRejected=!!receipt&&!success;
 const payload=()=>mode==='paste'
   ?{fixtures_text:paste,target_odds:Number(target)}
   :{selections:selected.map(({event_id,market_id,specifier,outcome_id})=>({event_id,market_id,specifier,outcome_id})),target_odds:Number(target)};
 const inspect=async()=>{
   if(lock.current||!ready)return;
   lock.current=true;setBusy('preview');setNotice('');setQuote(null);setReceipt(null);setConfirm(false);
   try{
     const result=await api<Quote>(mode==='paste'?'basketball-jackpot/paste-preview':'basketball-jackpot/preview',payload(),'POST');
     setQuote(result);
     if(result.status!=='PROPOSED_NOT_BOOKED')setNotice(result.reason||'The ticket is not fully verified at your target odds.');
   }catch(e){setNotice(errorText(e));}finally{lock.current=false;setBusy(null);}
 };
 const generate=async()=>{
   if(lock.current||!complete||receipt||bookingAttempted)return;
   if(!confirm){setConfirm(true);return;}
   // Set the tab-level latch BEFORE any network request. Even an interrupted
   // request may have created a share code, so reloading must not unlock POST.
   setBookingAttempted(true);
   try{window.sessionStorage.setItem(DRAFT_KEY,JSON.stringify({
     mode,paste,selected,target,booking_attempted:true,updated_at:Date.now()} satisfies TicketDraft));}catch{}
   lock.current=true;setBusy('book');setNotice('');setReceipt(null);
   try{
     const result=await api<Quote>(mode==='paste'?'basketball-jackpot/paste-book':'basketball-jackpot/book',payload(),'POST');
     setReceipt(result);
     void loadHistory();
     if(result.status!=='success'||!result.share_code||result.readback_status!=='PASSED')
       setNotice(result.reason||'SportyBet did not confirm a complete share code.');
   }catch(e){setNotice(errorText(e)+' Do not repeat an uncertain share-code request before checking SportyBet.');}
   finally{lock.current=false;setBusy(null);setConfirm(false);}
 };
 const leagueCoverage=useMemo(()=>{
   if(board?.status!=='success')return [] as {name:string;games:number;teams:number}[];
   const leagues=new Map<string,{games:number;teams:Set<string>}>();
   for(const item of board.fixtures){
     const name=item.competition?.trim();
     if(!name)continue;
     if(!leagues.has(name))leagues.set(name,{games:0,teams:new Set<string>()});
     const entry=leagues.get(name)!;
     entry.games++;
     entry.teams.add(item.home_team);
     entry.teams.add(item.away_team);
   }
   return [...leagues.entries()].map(([name,val])=>({
     name,games:val.games,teams:val.teams.size,
   })).sort((a,b)=>b.games-a.games||a.name.localeCompare(b.name));
 },[board]);
 return <div className="bj">
   <header className="bj-hero">
     <div className="bj-hero-main">
       <div className="bj-eyebrow"><span className="bj-live-dot"/> PRIVATE BOOKMAKER DESK <span> / </span> BASKETBALL</div>
       <h1>Basketball <em>Jackpot.</em></h1>
       <p>Build your ticket. Verify every market. Generate a SportyBet code only after the full selection passes readback.</p>
       <div className="bj-hero-tags"><span><ShieldCheck size={14}/> Admin protected</span><span><Ticket size={14}/> No stake placed</span><span><Clock3 size={14}/> WAT timezone</span></div>
     </div>
     <div className="bj-hero-side"><div className="bj-hero-caption">BOOKMAKER BOARD</div>
       <strong>{board?.status==='success'?(board.fixtures.length).toLocaleString('en-NG'):'—'}</strong><span>Upcoming priced games</span>
       <button type="button" className="bj-refresh" disabled={busy!==null} onClick={refresh}>
         {busy==='refresh'?<Loader2 className="spin" size={15}/>:<RefreshCcw size={15}/>}
         {busy==='refresh'?'Refreshing…':'Refresh prices'}
       </button>
     </div>
   </header>

   <section className="bj-coverage" aria-label="Live basketball team and league coverage">
     <div><strong>Competitions available on this bookmaker board</strong>
       <p>{leagueCoverage.length
         ?leagueCoverage.length+' basketball leagues, from the last complete bookmaker snapshot. NBA alone has private prediction research; all other teams are bookmaker-only.'
         :'No verified league inventory yet. Refresh the complete bookmaker board.'}</p></div>
     {leagueCoverage.length>0&&<div className="bj-coverage-leagues">
       {leagueCoverage.slice(0,9).map(item=><span key={item.name} title={item.teams+' unique teams'}>
         {item.name} · {item.games} games</span>)}
       {leagueCoverage.length>9&&<span>+{leagueCoverage.length-9} more in All</span>}
     </div>}
   </section>

   {restored.current&&(restored.current.paste.trim()||restored.current.selected.length>0)&&
      <div className="bj-inline-warning" role="status">
        An unsent ticket draft was restored from this browser tab. Its prices and bookmaker status are NOT verified. Run Preview before any booking action.
      </div>}
   <div className="bj-stats">
     <div><span>SELECTIONS</span><strong>{legCount}<small> / 50</small></strong></div>
     <div><span>TARGET ODDS</span><strong>{allowedTarget?odds(target)+'x':'—'}</strong></div>
     <div><span>BOOKMAKER CHECK</span><strong className={complete&&!bookingRejected?'bj-green':''}>{bookingRejected?'Re-preview required':complete?'Ready to confirm':quote?'Needs attention':'Not checked'}</strong></div>
     <div><span>CODE STATUS</span><strong className={success?'bj-green':''}>{success?'Verified':bookingRejected?'Not released':'Not verified'}</strong></div>
   </div>

   {busy&&<div className="bj-progress" role="status"><Loader2 size={17} className="spin"/>{busyCopy[busy]}</div>}
   {board?.status!=='success'&&busy!=='load'&&!complete&&!success&&<div className="bj-alert" role="alert">
     <AlertCircle size={18}/><span>{board?.reason||'No complete basketball snapshot. Refresh the bookmaker board first.'}</span>
     {board?.status==='SERVICE_UNAVAILABLE'&&<button type="button" disabled={busy!==null} onClick={()=>void load()}>
       <RefreshCcw size={15}/> Retry connection</button>}
   </div>}

   <div className="bj-columns">
     <section className="bj-workspace">
       <div className="bj-section-top"><div><span className="bj-overline">01 / BUILD TICKET</span><h2>Choose how to add games</h2><p>Manual picks only. No automatic or substituted selections.</p></div></div>
       <div className="bj-tabs" role="tablist" aria-label="Basketball ticket editing">
         <button role="tab" aria-selected={mode==='paste'} type="button" className={mode==='paste'?'active':''}
           onClick={()=>switchMode('paste')}><ClipboardPaste size={17}/> Paste exact picks</button>
         <button role="tab" aria-selected={mode==='browse'} type="button" className={mode==='browse'?'active':''}
           onClick={()=>switchMode('browse')}><LayoutGrid size={17}/> Browse fixtures</button>
       </div>

       {mode==='paste'?<div className="bj-paste-panel">
         <div className="bj-input-heading"><strong>Paste fixtures and markets</strong><span>One exact pick per line</span></div>
         <textarea spellCheck={false} rows={10} disabled={busy!==null} value={paste}
           onChange={e=>{setPaste(e.target.value);edit();}} placeholder={samples.join('\n')} aria-label="Basketball fixtures and exact selections"/>
         <div className="bj-paste-foot"><span>{lineCount} of 50 lines</span><button type="button" disabled={!paste||busy!==null}
           onClick={()=>{setPaste('');edit();}}><Trash2 size={14}/> Clear text</button></div>
         <div className="bj-format"><div><FileCheck2 size={18}/><strong>Supported format</strong></div>
           <code>Team A vs Team B | Home win</code>
           <code>Team A vs Team B | Away win</code>
           <code>Team A vs Team B | Over 221.5</code>
           <code>Team A vs Team B | Under 221.5</code>
           <p>Pasted @odds are ignored. Exact teams, moneyline outcomes and points lines are checked against the current SportyBet board. A rejected line never becomes a different pick.</p>
         </div>
       </div>:<div className="bj-browse">
         <div className="bj-filters">
           <label className="bj-search"><Search size={17}/><input placeholder="Search teams or competitions…" value={search}
             onChange={e=>{setSearch(e.target.value);setLimit(14);}}/></label>
           <div className="bj-filterrow">{(['Featured','NBA','All','Women'] as const).map(item=>
             <button key={item} type="button" className={filter===item?'active':''}
               onClick={()=>{setFilter(item);setLimit(14);}}>{item}</button>)}</div>
         </div>
         <div className="bj-fixture-count">{shown.length} matching upcoming fixtures. Choose one exact selection per match.</div>
         <div className="bj-fixtures">{shown.slice(0,limit).map(event=><div className="bj-fixture" key={event.event_id}>
           <div className="bj-fixture-main"><div><span className="bj-league">{event.competition}</span>
             <strong>{event.home_team} <span>vs</span> {event.away_team}</strong></div>
             <time>{time(event.kickoff_ms)}</time></div>
           <select value="" aria-label={'Pick market for '+eventTitle(event)} disabled={busy!==null||selected.some(p=>p.event_id===event.event_id)}
             onChange={e=>add(event,e.target.value)}><option value="">{selected.some(p=>p.event_id===event.event_id)?'Already added':'Select a market & outcome'}</option>
             {event.markets.map(m=><optgroup key={m.market_id+'|'+m.specifier} label={m.label+' '+m.specifier}>
               {m.outcomes.map(o=><option key={o.outcome_id} value={[m.market_id,m.specifier,o.outcome_id].join('~')}>{o.label} · {odds(o.odds)}x</option>)}
             </optgroup>)}</select>
         </div>)}</div>
         {shown.length===0&&<div className="bj-empty"><Database size={25}/><p>No fixtures match this filter. Try All or a different search.</p></div>}
         {shown.length>limit&&<button type="button" className="bj-more" onClick={()=>setLimit(v=>v+20)}>Show more games ({shown.length-limit} remaining) <ArrowRight size={16}/></button>}
       </div>}
     </section>

     <aside className="bj-ticket">
       <div className="bj-section-top"><div><span className="bj-overline">02 / VERIFY & GENERATE</span><h2>Ticket workspace</h2><p>{mode==='paste'?'Your exact pasted selections':'Your selected bookmaker outcomes'}</p></div><Ticket size={23}/></div>
       {mode==='browse'&&<div className="bj-ticket-list">{selected.length?selected.map((p,i)=><div className="bj-ticket-leg" key={p.event_id}>
         <span>{String(i+1).padStart(2,'0')}</span><div><strong>{p.fixture}</strong><small>{p.label}</small></div><b>{odds(p.odds)}x</b>
         <button type="button" aria-label={'Remove '+p.fixture} disabled={busy!==null} onClick={()=>{setSelected(v=>v.filter(x=>x.event_id!==p.event_id));edit();}}>×</button>
       </div>):<div className="bj-empty"><Ticket size={26}/><p>No picks yet. Select fixtures from the board.</p></div>}</div>}
       {mode==='paste'&&<div className="bj-ticket-callout"><ClipboardPaste size={19}/><div><strong>{lineCount?lineCount+' pasted selections':'No picks pasted yet'}</strong><p>{lineCount?'Use Preview to validate every game, market and price.':'Paste your selections on the left to begin.'}</p></div></div>}
       <div className="bj-ticket-total"><span>{mode==='browse'?'Unverified board estimate':'Full-ticket reference price'}</span>
         <strong>{mode==='browse'?odds(total)+'x':quote?.indicative_odds?odds(quote.indicative_odds)+'x':'Pending preview'}</strong>
         <small>Only a completed bookmaker readback confirms a booking.</small>
       </div>
       <label className="bj-target">Minimum accumulator odds <input type="number" min="2" max="100000" step=".01" value={target}
         disabled={busy!==null} onChange={e=>{setTarget(e.target.value);edit();}}/></label>
       <div className="bj-quick">{[2,5,10,100,1000].map(v=><button type="button" key={v} disabled={busy!==null}
         className={Number(target)===v?'active':''} onClick={()=>{setTarget(String(v));edit();}}>{v.toLocaleString()}x</button>)}</div>
       <div className="bj-actions">
         <button type="button" className="bj-button bj-button-outline" disabled={!ready||busy!==null} onClick={inspect}>
           {busy==='preview'?<Loader2 className="spin" size={17}/>:<ShieldCheck size={17}/>} Preview exact picks</button>
         <button type="button" className="bj-button bj-button-primary" disabled={!complete||busy!==null||!!receipt||bookingAttempted} onClick={generate}>
           {busy==='book'?<Loader2 className="spin" size={17}/>:<ArrowRight size={17}/>}
           {confirm?'Confirm code request':'Generate SportyBet code'}</button>
       </div>
       {bookingAttempted&&<div className="bj-inline-warning" role="alert">This draft has already sent a share-code request or its outcome is uncertain. Check Booking History and recover the existing code; do not generate another.</div>}
       {confirm&&<div className="bj-inline-warning">This makes one bookmaker share-code request for your verified ticket. It does not place a stake.</div>}
       {quote&&<div className={'bj-quote '+(complete?'bj-quote-good':'bj-quote-bad')} role="status">
         <strong>{complete?<CheckCircle2 size={18}/>:<AlertCircle size={18}/>} {complete?'Ready for confirmation':quote.status}</strong>
         <p>{quote.matched_fixture_count??0} / {legCount} matched. {quote.full_ticket_complete?'Complete ticket.':'Some selections require attention.'}
          {quote.indicative_odds?' Reference '+odds(quote.indicative_odds)+'x.':''}</p>
         {quote.unmatched?.map(x=><p className="bj-quote-error" key={x.line}>Line {x.line}: {x.reason.replaceAll('_',' ').toLowerCase()}{x.detail?' — '+x.detail:''}</p>)}
       </div>}
       {bookingRejected&&<div className="bj-inline-warning" role="alert"><AlertCircle size={16}/>
         <span>SportyBet code has not passed all checks. No code was released.
         {receipt?.verified_odds!=null?' Current quote: '+odds(receipt.verified_odds)+'x.':''}
         {' '}Review the reason, then open Booking History and use Recheck existing code. Do not generate a duplicate.</span>
       </div>}
       {notice&&<div className="bj-inline-warning" role="alert"><AlertCircle size={16}/>{notice}</div>}
       {success&&<div className="bj-success" role="status"><CheckCircle2 size={20}/><p>SPORTYBET READBACK VERIFIED</p>
         <strong>{receipt?.share_code}</strong><span>{receipt?.legs} exact picks · {odds(receipt?.verified_odds)}x verified
         {receipt?.verified_odds_source==='fresh_complete_sportybet_board'
           ?' (fresh bookmaker board price; legs verified by code readback)'
           :' (code readback price)'}</span>
         <button type="button" onClick={()=>receipt?.share_code&&navigator.clipboard.writeText(receipt.share_code)}><Clipboard size={15}/> Copy code</button>
       </div>}
       <div className="bj-disclaimer"><Activity size={16}/><p>Bookmaker-only manual experiment. Price availability is not a prediction of success. No bets or stakes are placed here.</p></div>
     </aside>
   </div>
   <section className="bj-history" aria-label="Saved basketball jackpot codes and results">
     <div className="bj-history-head">
       <div><span className="bj-overline">03 / DURABLE RECORDS</span>
         <h2>Basketball booking history</h2>
         <p>Saved SportyBet codes, exact markets and verified results. NBA finals are checked automatically; other leagues stay pending until supported.</p></div>
       <div className="bj-history-actions">
         <button type="button" disabled={historyBusy!==null} onClick={()=>void loadHistory()}>
           <RefreshCcw size={15}/> Refresh history</button>
         <button type="button" disabled={historyBusy!==null} onClick={()=>void settleHistory()}>
           {historyBusy==='settling'?<Loader2 size={15} className="spin"/>:<ShieldCheck size={15}/>} Verify NBA finals</button>
       </div>
     </div>
     {historyBusy&&<div className="bj-progress" role="status">
       <Loader2 size={16} className="spin"/>{historyBusy==='settling'?'Checking confirmed NBA final scores…':'Loading saved codes…'}</div>}
     {historyError&&<div className="bj-inline-warning" role="alert">{historyError}</div>}
     {historyInfo&&<div className="bj-quote bj-quote-good" role="status">{historyInfo}</div>}
     {!historyRows.length&&!historyBusy&&!historyError&&<div className="bj-empty">
       <Database size={23}/><p>The connected backend returned zero basketball booking attempts. A previously attempted code cannot be recovered from this empty history. Do not create a duplicate until the original backend ledger is reconciled.</p></div>}
     <div className="bj-history-list">{historyRows.map(ticket=><details key={ticket.fingerprint} className="bj-history-ticket">
       <summary><span className="bj-history-code">{ticket.share_code||'Attempt recorded'}</span>
         <span>{ticket.leg_count} games</span>
         <span>{ticket.verified_odds!=null?odds(ticket.verified_odds)+'x':'Price pending'}</span>
         <strong className={ticket.status==='won'?'bj-h-won':ticket.status==='lost'?'bj-h-lost':''}>{ticket.detail?.ticket_status&&ticket.status==='active'
             ?ticket.detail.ticket_status.replaceAll('_',' '):ticket.status.replaceAll('_',' ')}</strong></summary>
       <div className="bj-history-detail">
         <p>Created {new Date(ticket.created_at).toLocaleString('en-NG',{timeZone:'Africa/Lagos'})}
         {ticket.expires_at?' · Code expiry '+new Date(ticket.expires_at).toLocaleString('en-NG',{timeZone:'Africa/Lagos'}):''}
         {ticket.last_checked_at?' · Score check '+new Date(ticket.last_checked_at).toLocaleString('en-NG',{timeZone:'Africa/Lagos'}):''}</p>
         {['needs_review','verifying'].includes(ticket.status)&&<button type="button" className="bj-history-copy" disabled={!!recovering||!!historyBusy} onClick={()=>void recoverSaved(ticket.fingerprint)}>
           {recovering===ticket.fingerprint?<Loader2 size={14} className="spin"/>:<ShieldCheck size={14}/>}
           {recovering===ticket.fingerprint?'Rechecking saved code…':'Recheck existing code · no new booking'}</button>}
         {ticket.share_code&&<button type="button" className="bj-history-copy" onClick={()=>navigator.clipboard.writeText(ticket.share_code||'')}>
           <Clipboard size={14}/> Copy saved code</button>}
         {ticket.detail?.reason&&<p className="bj-history-error">{ticket.detail.reason}</p>}
         {ticket.legs.map((leg,i)=><div className="bj-history-leg" key={i}>
           <span>{i+1}. {leg.home_team} vs {leg.away_team}
             <small>{leg.competition||'Basketball'} · {leg.selection} @{odds(leg.odds)}</small></span>
           <strong>{leg.result||'pending'}{leg.score?' · '+leg.score.home+'–'+leg.score.away:''}</strong>
         </div>)}
       </div>
     </details>)}</div>
     <p className="bj-history-note">Only results supported by uniquely matched, completed games can settle a leg. This history begins with bookings recorded after the ledger was introduced; earlier codes are not automatically imported.</p>
   </section>
 </div>;
}