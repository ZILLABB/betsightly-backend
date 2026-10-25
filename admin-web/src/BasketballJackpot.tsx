import React, {useEffect, useMemo, useRef, useState} from 'react';
import {CheckCircle2, Clipboard, Loader2, RefreshCcw, ShieldCheck, Trash2} from 'lucide-react';
import {api} from './api';

type Outcome={outcome_id:string;label:string;odds:number};
type Market={market_id:string;specifier:string;label:string;outcomes:Outcome[]};
type Fixture={event_id:string;home_team:string;away_team:string;competition:string;kickoff_ms:number;markets:Market[]};
type Pick={event_id:string;market_id:string;outcome_id:string;specifier:string;label:string;fixture:string;odds:number};
type Board={status:string;reason?:string;fixtures:Fixture[];fetched_at?:number;metadata?:{snapshot_id?:string}};
type Preview={status:string;reason?:string;indicative_odds?:number;verified_odds?:number;matched_fixture_count?:number;
  full_ticket_complete?:boolean;target_odds?:number;share_code?:string|null;readback_status?:string;unmatched?:{line:number;reason:string}[];share_url?:string;legs?:number};

const short=(error:unknown)=>error instanceof Error?error.message:'An unexpected request error occurred';
const number=(n:number)=>Number.isFinite(n)?n.toLocaleString('en-NG',{maximumFractionDigits:3}):'—';
const time=(ms:number)=>new Date(ms).toLocaleString('en-NG',{timeZone:'Africa/Lagos',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
const pickId=(p:Pick)=>[p.event_id,p.market_id,p.specifier,p.outcome_id].join('|');

export default function BasketballJackpot(){
 const [board,setBoard]=useState<Board|null>(null);
 const [search,setSearch]=useState('');
 const [selected,setSelected]=useState<Pick[]>([]);
 const [target,setTarget]=useState('100');
 const [preview,setPreview]=useState<Preview|null>(null);
 const [booking,setBooking]=useState<Preview|null>(null);
 const [message,setMessage]=useState('');
 const [busy,setBusy]=useState<'load'|'refresh'|'preview'|'book'|null>(null);
 const [confirmed,setConfirmed]=useState(false);
 const busyLock=useRef(false);
 const load=async()=>{
   if(busyLock.current)return;
   busyLock.current=true;setBusy('load');setMessage('');
   try{const data=await api<Board>('basketball-jackpot/board');setBoard(data);}
   catch(e){setMessage(short(e));}
   finally{setBusy(null);busyLock.current=false;}
 };
 useEffect(()=>{void load();},[]);
 const refresh=async()=>{
   if(busyLock.current)return;
   busyLock.current=true;setBusy('refresh');setMessage('');setPreview(null);setBooking(null);setConfirmed(false);
   try{
     const result=await api<{status:string;reason?:string}>('basketball-jackpot/refresh',{},'POST');
     const data=await api<Board>('basketball-jackpot/board');
     setBoard(data);
     if(result.status!=='success')setMessage(result.reason||'Basketball feed incomplete. Previous complete board was preserved.');
   }catch(e){setMessage(short(e));}
   finally{setBusy(null);busyLock.current=false;}
 };
 const clearPreview=()=>{setPreview(null);setBooking(null);setConfirmed(false);setMessage('');};
 const add=(event:Fixture,value:string)=>{
   if(!value)return;
   const [mid,spec,oid]=value.split('|');
   const market=event.markets.find(m=>m.market_id===mid&&m.specifier===spec);
   const outcome=market?.outcomes.find(o=>o.outcome_id===oid);
   if(!market||!outcome)return;
   setSelected(before=>{
     if(before.some(p=>p.event_id===event.event_id))return before;
     if(before.length>=50)return before;
     return [...before,{event_id:event.event_id,market_id:mid,specifier:spec,outcome_id:oid,
       label:outcome.label,fixture:event.home_team+' vs '+event.away_team,odds:outcome.odds}];
   });
   clearPreview();
 };
 const remove=(id:string)=>{setSelected(s=>s.filter(p=>p.event_id!==id));clearPreview();};
 const filtered=useMemo(()=>((board?.fixtures||[]).filter(f=>(f.home_team+' '+f.away_team+' '+f.competition)
   .toLowerCase().includes(search.toLowerCase())).sort((a,b)=>a.kickoff_ms-b.kickoff_ms)),[board,search]);
 const selections=()=>selected.map(({event_id,market_id,outcome_id,specifier})=>({event_id,market_id,outcome_id,specifier}));
 const payload=()=>({selections:selections(),target_odds:Number(target)});
 const valid=selected.length>0&&Number.isFinite(Number(target))&&Number(target)>=2&&Number(target)<=100000;
 const inspect=async()=>{
   if(busyLock.current||!valid)return;
   busyLock.current=true;setBusy('preview');setMessage('');setBooking(null);setConfirmed(false);
   try{const r=await api<Preview>('basketball-jackpot/preview',payload(),'POST');setPreview(r);
     if(r.status!=='PROPOSED_NOT_BOOKED')setMessage(r.reason||'The ticket did not clear exact bookmaker validation or target odds.');
   }catch(e){setPreview(null);setMessage(short(e));}
   finally{setBusy(null);busyLock.current=false;}
 };
 const makeCode=async()=>{
   if(busyLock.current||preview?.status!=='PROPOSED_NOT_BOOKED'||!preview.full_ticket_complete)return;
   if(!confirmed){setConfirmed(true);return;}
   busyLock.current=true;setBusy('book');setMessage('');setBooking(null);
   try{
     const result=await api<Preview>('basketball-jackpot/book',payload(),'POST');setBooking(result);
     if(result.status!=='success'||!result.share_code||result.readback_status!=='PASSED')
       setMessage(result.reason||'No bookmaker code was verified. No code released.');
   }catch(e){setMessage(short(e)+' If network status is uncertain, inspect the bookmaker before retrying.');}
   finally{setBusy(null);busyLock.current=false;setConfirmed(false);}
 };
 const referenceTotal=selected.reduce((a,p)=>a*p.odds,1);
 const success=booking?.status==='success'&&!!booking.share_code&&booking.readback_status==='PASSED';
 return <>
   <div className="page-heading"><div><span className="eyebrow">PRIVATE · BASKETBALL · BOOKMAKER-VERIFIED</span>
     <h1>Basketball Jackpot Studio.</h1>
     <p>Build an exact manual basketball accumulator from active SportyBet markets. No stake, auto-prediction, football-tier interference, or unverified booking code.</p></div></div>
   <section className="panel"><header className="panel-head"><div><h2>Basketball bookmaker board</h2>
     <p>Only real basketball fixtures and exact active full-game markets are shown. eBasketball is excluded.</p></div>
     <button className="button secondary" type="button" disabled={busy!==null} onClick={refresh}>{busy==='refresh'?<Loader2 size={17} className="spin"/>:<RefreshCcw size={17}/>} Refresh basketball board</button>
   </header>
   {busy==='load'&&<div className="notice info" role="status"><Loader2 size={17} className="spin"/> Loading saved basketball prices…</div>}
   {board?.status!=='success'&&busy!=='load'&&<div className="notice warning" role="status">{board?.reason||'No completed basketball bookmaker snapshot. Use Refresh basketball board first.'}</div>}
   {board?.status==='success'&&<div className="notice info" role="status"><ShieldCheck size={17}/><div>{board.fixtures.length} upcoming bookmaker fixtures · complete cached snapshot {board.metadata?.snapshot_id||'available'} · indicative prices are verified again before code release.</div></div>}
   <label>Filter games<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Team or competition e.g. NBA"/></label>
   <div className="scroll-table" style={{maxHeight:470,overflow:'auto'}}>
     <table><thead><tr><th>Fixture</th><th>Starts (WAT)</th><th>Add exact selection</th></tr></thead><tbody>
       {filtered.slice(0,120).map(f=><tr key={f.event_id}>
         <td><strong>{f.home_team} vs {f.away_team}</strong><div className="muted">{f.competition}</div></td>
         <td>{time(f.kickoff_ms)}</td>
         <td><select value="" aria-label={'Choose market for '+f.home_team+' vs '+f.away_team}
           disabled={selected.some(p=>p.event_id===f.event_id)||busy!==null}
           onChange={e=>add(f,e.target.value)}>
           <option value="">Choose moneyline or total points</option>
           {f.markets.map(m=><optgroup label={m.label+(m.specifier?' · '+m.specifier:'')} key={m.market_id+'|'+m.specifier}>
             {m.outcomes.map(o=><option value={[m.market_id,m.specifier,o.outcome_id].join('|')} key={o.outcome_id}>
               {o.label} @ {number(o.odds)}
             </option>)}</optgroup>)}
           </select></td>
       </tr>)}
     </tbody></table>
   </div>
   {filtered.length>120&&<p className="muted">Showing first 120 matching fixtures. Narrow the filter to find more.</p>}
   </section>
   <section className="panel"><header className="panel-head"><div><h2>Your private basketball ticket</h2>
     <p>One market per fixture, up to 50 legs. Markets are never substituted silently.</p></div>
     <button type="button" className="button secondary" disabled={busy!==null||!selected.length}
       onClick={()=>{setSelected([]);clearPreview();}}><Trash2 size={17}/> Clear</button>
   </header>
   {selected.length?<>
     <div className="scroll-table"><table><thead><tr><th>#</th><th>Match</th><th>Selected outcome</th><th>Cached price</th><th></th></tr></thead><tbody>
       {selected.map((p,i)=><tr key={pickId(p)}><td>{i+1}</td><td>{p.fixture}</td><td>{p.label}</td><td>{number(p.odds)}</td>
         <td><button className="mini-button" disabled={busy!==null} onClick={()=>remove(p.event_id)}>Remove</button></td></tr>)}
     </tbody></table></div>
     <div className="data-rows"><div><span>Selected fixtures</span><b>{selected.length}</b></div>
       <div><span>Reference accumulator odds</span><b>{number(referenceTotal)}x</b></div></div>
   </>:<div className="empty">Choose an active market from the basketball fixture list above.</div>}
   <label>Minimum total odds (2–100,000x)<input type="number" min="2" max="100000" step=".01"
      value={target} onChange={e=>{setTarget(e.target.value);clearPreview();}}/></label>
   <div className="toolbar">
     <button type="button" className="button secondary" disabled={!valid||busy!==null} onClick={inspect}>
       {busy==='preview'?<Loader2 size={17} className="spin"/>:<ShieldCheck size={17}/>} Preview exact basketball ticket</button>
     <button type="button" className="button primary" disabled={!valid||busy!==null||preview?.status!=='PROPOSED_NOT_BOOKED'||!preview.full_ticket_complete||success}
       onClick={makeCode}>{busy==='book'?<Loader2 size={17} className="spin"/>:<CheckCircle2 size={17}/>}
       {confirmed?'Confirm SportyBet code reservation':'Generate verified booking code'}</button>
   </div>
   {confirmed&&<div className="notice warning" role="status">Confirm one anonymous SportyBet booking-code request for {selected.length} exact basketball legs. This never stakes money.</div>}
   {preview&&<div className={'notice '+(preview.status==='PROPOSED_NOT_BOOKED'?'success':'warning')} role="status">
     <ShieldCheck size={17}/><div><strong>{preview.status}</strong> · {preview.matched_fixture_count||0}/{selected.length} matched ·
      {preview.full_ticket_complete?' complete preview':' incomplete ticket'} · Reference quote {number(Number(preview.indicative_odds||0))}x
      {preview.unmatched?.map(u=><div key={u.line}>Leg {u.line}: {u.reason}</div>)}</div></div>}
   {message&&<div className="notice warning" role="alert">{message}</div>}
   {success&&<div className="notice success" role="status"><CheckCircle2 size={19}/><div>
     <h3>SportyBet booking code verified</h3><strong style={{fontSize:30,letterSpacing:3}}>{booking?.share_code}</strong>
     <p>Exact {booking?.legs} legs passed bookmaker readback · Verified {number(Number(booking?.verified_odds||0))}x</p>
     <button type="button" className="mini-button" onClick={()=>booking?.share_code&&navigator.clipboard.writeText(booking.share_code)}>
       <Clipboard size={16}/> Copy code</button>
     </div></div>}
   </section>
 </>;
}
