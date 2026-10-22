import React, {useMemo, useRef, useState} from 'react';
import {AlertTriangle, CheckCircle2, Clipboard, Loader2, RefreshCcw, Search, ShieldCheck, Target} from 'lucide-react';
import {api} from './api';

type Candidate = {
 selection_id:string;match_id:string;home_team:string;away_team:string;league?:string;
 kickoff?:string;market:string;odds:number;selection_probability?:number;
 lower_reliability_bound?:number;trust_grade?:string;recommended_for_fixture?:boolean;
 expected_value?:number;
};
type Board = {status:string;reason?:string;candidate_count?:number;candidates?:Candidate[];board?:any};
type Booking = {status:string;reason?:string;share_code?:string;share_url?:string;verified_odds?:number;
 legs?:number;readback_status?:string;expires_at?:string;estimated_all_leg_probability?:number;
 publication_status?:string;indicative_odds?:number;invalid_selections?:any[]};
const number = (x:number, digits=2)=>x.toLocaleString('en-NG',{maximumFractionDigits:digits,minimumFractionDigits:digits});
const errorText=(e:unknown)=>e instanceof Error?e.message:'Request could not be completed.';

export default function PrivateJackpot() {
 const [horizon,setHorizon]=useState('today');
 const [grade,setGrade]=useState('B');
 const [query,setQuery]=useState('');
 const [target,setTarget]=useState('100000');
 const [board,setBoard]=useState<Board|null>(null);
 const [selected,setSelected]=useState<string[]>([]);
 const [loading,setLoading]=useState(false);
 const [booking,setBooking]=useState<Booking|null>(null);
 const [bookingBusy,setBookingBusy]=useState(false);
 const [message,setMessage]=useState('');
 const latch=useRef(false);
 const rows=board?.candidates||[];
 const selections=useMemo(()=>selected.map(k=>rows.find(x=>x.selection_id===k)).filter((x):x is Candidate=>!!x),[selected,rows]);
 const indicative=selections.reduce((p,c)=>p*Number(c.odds||1),1);
 const probability=selections.reduce((p,c)=>p*Number(c.selection_probability||0),1);
 const desired=Number(target);
 const acceptable=Number.isFinite(desired)&&desired>=2&&desired<=100000;
 const canBook=selections.length>0&&selections.length<=50&&acceptable&&indicative>=desired&&!bookingBusy&&!loading;
 const filtered=useMemo(()=>{
   const s=query.trim().toLowerCase();
   return rows.filter(r=>!s||[r.home_team,r.away_team,r.league,r.market].join(' ').toLowerCase().includes(s));
 },[rows,query]);
 const filters=()=>({horizon,min_trust_grade:grade,min_probability:.65,markets:[]});
 const fetchBoard=async()=>{
   if(latch.current)return;latch.current=true;setLoading(true);setMessage('');setBooking(null);setSelected([]);
   try{
     const result=await api<Board>('private-jackpot/candidates',filters(),'POST');
     setBoard(result);if(result.status!=='success')setMessage(result.reason||'The bookable candidate board is not ready.');
   }catch(e){setBoard(null);setMessage(errorText(e));}
   finally{latch.current=false;setLoading(false);}
 };
 const toggle=(pick:Candidate)=>{
   if(bookingBusy)return;setBooking(null);setMessage('');
   setSelected(before=>{
     if(before.includes(pick.selection_id))return before.filter(x=>x!==pick.selection_id);
     const withoutFixture=before.filter(x=>rows.find(r=>r.selection_id===x)?.match_id!==pick.match_id);
     if(withoutFixture.length>=50)return before;
     return [...withoutFixture,pick.selection_id];
   });
 };
 const book=async()=>{
   if(latch.current||!canBook)return;
   if(!window.confirm('Request a real SportyBet share code for '+selections.length+' approved fixtures at a minimum '+number(desired,0)+'x? No bet or public publication will occur.'))return;
   latch.current=true;setBookingBusy(true);setMessage('');setBooking(null);
   try{
     const answer=await api<Booking>('private-jackpot/book',{...filters(),selection_ids:selected,target_odds:desired},'POST');
     setBooking(answer);
     if(answer.status!=='success'||!answer.share_code||answer.readback_status!=='PASSED')setMessage(answer.reason||'Bookmaker verification did not confirm a complete ticket. No code released.');
   }catch(e){setMessage(errorText(e)+' Do not immediately repeat a request after a timeout; first verify whether SportyBet already created a code.');}
   finally{latch.current=false;setBookingBusy(false);}
 };
 return <>
  <div className="page-heading"><div><span className="eyebrow">PRIVATE · BOOKMAKER-VERIFIED</span><h1>Smart Jackpot Studio.</h1><p>Research-informed selections, exact-leg verification and private SportyBet booking codes. Nothing publishes to the public website.</p></div></div>
  <section className="panel">
   <header className="panel-head"><div><h2>Choose your qualified match board</h2><p>Uses the existing BetSightly calibration, trust and bookmaker-bookability gates.</p></div><ShieldCheck size={21}/></header>
   <fieldset className="editor" disabled={loading||bookingBusy}>
    <div className="jackpot-controls">
     <label>Fixture window<select value={horizon} onChange={e=>{setHorizon(e.target.value);setBoard(null);setSelected([]);setBooking(null);}}><option value="today">Today only</option><option value="3_days">Next 3 days</option><option value="7_days">Next 7 days</option></select></label>
     <label>Minimum model trust<select value={grade} onChange={e=>{setGrade(e.target.value);setBoard(null);setSelected([]);setBooking(null);}}><option value="B">B or A</option><option value="A">A only</option></select></label>
     <label>Minimum verified combined odds<input type="number" value={target} min={2} max={100000} step="any" onChange={e=>{setTarget(e.target.value);setBooking(null);}}/></label>
    </div>
    <button type="button" className="button primary" disabled={loading} onClick={fetchBoard}>{loading?<Loader2 size={17} className="spin"/>:<RefreshCcw size={17}/>} {loading?'Loading bookmaker-qualified matches…':'Load approved matches'}</button>
   </fieldset>
   <div className="notice info"><ShieldCheck size={17}/><div>Admin-only. No under-goals markets, no duplicate fixtures and no forced weak legs. SportyBet prices may move; 100,000x is a very low-probability target.</div></div>
   {message&&<div role="alert" className="notice warning"><AlertTriangle size={17}/><div>{message}</div></div>}
  </section>
  {board?.status==='success'&&<div className="split jackpot-layout">
   <section className="panel">
    <header className="panel-head"><div><h2>Verified candidate board</h2><p>{board.candidate_count||0} approved selections · pick at most one market per match.</p></div></header>
    <label className="jackpot-search"><Search size={16}/><input aria-label="Search matches" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search team, league or market"/></label>
    <div className="jackpot-candidate-list">
     {filtered.slice(0,120).map(c=>{
       const checked=selected.includes(c.selection_id);
       const replaced=selected.some(id=>rows.find(x=>x.selection_id===id)?.match_id===c.match_id);
       return <button type="button" key={c.selection_id} disabled={bookingBusy} className={'jackpot-candidate '+(checked?'chosen':'')} onClick={()=>toggle(c)} aria-pressed={checked}>
        <span className="jackpot-selection-mark">{checked?'✓':replaced?'↺':'+'}</span>
        <span className="jackpot-candidate-label"><strong>{c.home_team} vs {c.away_team}</strong><small>{c.league||'Football'} · {c.market.replaceAll('_',' ')} · {c.trust_grade||'—'} trust</small></span>
        <span className="jackpot-candidate-price">{number(c.odds)}x</span>
       </button>
     })}
     {filtered.length>120&&<p className="muted">Showing the first 120 of {filtered.length} matches. Use search to narrow results.</p>}
     {!filtered.length&&<p className="empty">No matches match this search. Try another team or fixture window.</p>}
    </div>
   </section>
   <section className="panel">
    <header className="panel-head"><div><h2>Your private jackpot</h2><p>Selection preview only. No booking code is created until you explicitly confirm.</p></div><Target size={20}/></header>
    <div className="jackpot-totals">
     <div><span>Selected matches</span><strong>{selections.length} / 50</strong></div>
     <div><span>Combined reference odds</span><strong>{number(indicative)}x</strong></div>
     <div><span>Required minimum</span><strong>{acceptable?number(desired)+'x':'Invalid target'}</strong></div>
    </div>
    {selections.length>0&&<>
     <div className="jackpot-ticket-list">{selections.map((pick,i)=><div key={pick.selection_id} className="jackpot-ticket-item"><span>{i+1}. {pick.home_team} — {pick.away_team}<small>{pick.market.replaceAll('_',' ')} · {number(pick.odds)}x</small></span><button className="mini-button" type="button" disabled={bookingBusy} onClick={()=>toggle(pick)}>Remove</button></div>)}</div>
     <p className="muted">Approximate independent-leg model probability: {probability?String((probability*100).toPrecision(3))+'%':'Unavailable'}. Correlations and estimation error can make this unreliable.</p>
    </>}
    {selections.length===0&&<p className="empty">Choose approved match markets on the left.</p>}
    {selections.length>0&&indicative<desired&&<div className="notice warning"><AlertTriangle size={17}/><div>The selected reference odds do not reach your target. Add stronger justified picks or lower the target.</div></div>}
    <button className="button primary wide" type="button" onClick={book} disabled={!canBook}>{bookingBusy?<Loader2 size={18} className="spin"/>:<ShieldCheck size={18}/>} {bookingBusy?'Generating and checking exact code…':'Generate verified SportyBet code'}</button>
    {booking?.status==='success'&&booking.share_code&&booking.readback_status==='PASSED'&&<div className="jackpot-code" role="status">
      <p><CheckCircle2 size={18}/> All {booking.legs} legs verified by bookmaker</p>
      <strong>{booking.share_code}</strong>
      <div>Actual bookmaker odds: {number(Number(booking.verified_odds||0))}x</div>
      <button className="mini-button" type="button" onClick={()=>navigator.clipboard.writeText(booking.share_code||'')}><Clipboard size={16}/> Copy code</button>
      <small>Price timestamp and expiry are bookmaker-provided. Ticket stays private and does not place a bet.</small>
     </div>}
   </section>
  </div>}
 </>;
}
