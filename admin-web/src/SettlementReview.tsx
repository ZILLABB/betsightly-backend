import React, {useMemo, useState} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {AlertTriangle, CheckCircle2, ClipboardCheck, ExternalLink, Loader2, RefreshCcw, ShieldCheck} from 'lucide-react';
import {api} from './api';

type PendingLeg = {
  date:string; tier:string; event_id:string; home:string; away:string;
  kickoff:string|null;league:string|null;league_slug?:string|null;
  country?:string|null;country_basis?:string;source_candidates?:string[];
  pending_reason:string;review_category:string;overdue_48h:boolean;
};
type Queue = {total_pending_legs:number;overdue_48h:number;unique_events:number;
  review_categories:Record<string,number>;legs:PendingLeg[]};
type Proposal = {status:string;review_id:string;fixture:Record<string,string>;
  score_90:{home:number;away:number};evidence_url:string;message:string};
type Outcome = {status:string;review_id:string;event_id:string;legs_updated:number;
  changed_tickets:{date:string;tier:string;previous_result:string;result:string}[]};

const nice=(v:unknown)=>v==null?'—':String(v);
const why=(reason:string)=>({
  country_unknown:'No reliable country identity',
  source_unsupported:'No registered score source',
  source_recheck:'Provider result needs reconciliation',
  missing_kickoff:'Kickoff identity missing'
} as Record<string,string>)[reason]||reason;

export default function SettlementReview() {
 const qc=useQueryClient();
 const q=useQuery({queryKey:['manual-settlement-review'],queryFn:()=>api<Queue>('manual-tiers/settlement-review?limit=1000'),refetchOnMount:'always'});
 const [filter,setFilter]=useState(''), [selected,setSelected]=useState<PendingLeg|null>(null);
 const [homeScore,setHomeScore]=useState(''),[awayScore,setAwayScore]=useState('');
 const [url,setUrl]=useState(''),[note,setNote]=useState(''),[confirmation,setConfirmation]=useState('');
 const [attested,setAttested]=useState(false),[proposal,setProposal]=useState<Proposal|null>(null);
 const [busy,setBusy]=useState<'propose'|'approve'|null>(null);
 const [message,setMessage]=useState<{kind:'error'|'success'|'info';text:string}|null>(null);
 const [lastResult,setLastResult]=useState<Outcome|null>(null);
 const legs=q.data?.legs||[];
 const results=useMemo(()=>legs.filter(row=>[
    row.home,row.away,row.league,row.country,row.event_id,row.tier,row.date
  ].some(v=>String(v||'').toLowerCase().includes(filter.toLowerCase().trim()))),
  [legs,filter]);
 const choose=(row:PendingLeg)=>{
   setSelected(row);setHomeScore('');setAwayScore('');setUrl('');setNote('');
   setConfirmation('');setAttested(false);setProposal(null);setLastResult(null);setMessage(null);
 };
 const propose=async(e:React.FormEvent)=>{
   e.preventDefault();
   if(!selected||busy)return;
   setBusy('propose');setMessage({kind:'info',text:'Validating saved SportyBet event and recording proposal; no results will change.'});
   try{
     const result=await api<Proposal>('manual-tiers/settlement-review/propose',{
       publish_date:selected.date,tier:selected.tier,event_id:selected.event_id,
       home_score:Number(homeScore),away_score:Number(awayScore),
       evidence_url:url,evidence_note:note,
     });
     setProposal(result);setMessage({kind:'success',text:'Evidence proposal saved. Check the official match report independently and approve separately.'});
   }catch(error){setMessage({kind:'error',text:error instanceof Error?error.message:'Evidence proposal failed'});}
   finally{setBusy(null);}
 };
 const approve=async()=>{
   if(!proposal||!selected||busy)return;
   setBusy('approve');setMessage({kind:'info',text:'Rechecking exact bookmaker identity and saving auditable 90-minute grades…'});
   try{
     const result=await api<Outcome>('manual-tiers/settlement-review/approve',{
       review_id:proposal.review_id,confirmed_event_id:confirmation,
       attest_regulation_90:attested,
     });
     setLastResult(result);setProposal(null);setAttested(false);setConfirmation('');
     setMessage({kind:'success',text:'Confirmed '+result.legs_updated+' pending leg(s). Bookmaker codes and settled results were not overwritten.'});
     await q.refetch();void qc.invalidateQueries({queryKey:['manual-tiers']});
   }catch(error){setMessage({kind:'error',text:error instanceof Error?error.message:'Approval failed'});}
   finally{setBusy(null);}
 };
 return <div className="settlement-review-desk">
   <div className="page-heading"><div><span className="eyebrow">PROTECTED / VERIFIED SCORES</span>
      <h1>Settlement Evidence Desk.</h1>
      <p>Review unresolved manual legs, attach official 90-minute evidence, and approve only the exact saved event. No booking codes or model results are changed.</p>
    </div>
    <button type="button" className="mini-button" disabled={!!busy||q.isFetching}
      onClick={()=>void q.refetch()}>{q.isFetching?<Loader2 size={16} className="spin"/>:<RefreshCcw size={16}/>} Refresh pending</button>
   </div>
   <div className="metric-grid settlement-review-metrics">
    <div className="metric"><span>Pending manual legs</span><strong>{nice(q.data?.total_pending_legs)}</strong><small>Live saved records</small></div>
    <div className="metric"><span>Overdue 48 hours</span><strong>{nice(q.data?.overdue_48h)}</strong><small>Requires evidence recovery</small></div>
    <div className="metric"><span>Distinct pending events</span><strong>{nice(q.data?.unique_events)}</strong><small>Duplicate legs settle together only after approval</small></div>
   </div>
   {q.isError&&<div className="notice error" role="alert"><AlertTriangle size={18}/><div>Could not retrieve protected settlement queue: {q.error instanceof Error?q.error.message:'Unknown error'}</div></div>}
   {message&&<div className={'notice '+message.kind} role={message.kind==='error'?'alert':'status'}>
    {message.kind==='success'?<CheckCircle2 size={18}/>:message.kind==='error'?<AlertTriangle size={18}/>:<Loader2 size={18} className={busy?'spin':''}/>}
    <div>{message.text}</div></div>}
   {lastResult&&<div className="notice success" role="status">
     <ClipboardCheck size={19}/><div><strong>{lastResult.status}</strong>
       <p>Event {lastResult.event_id}; {lastResult.legs_updated} exact-event legs updated. A permanent proposal and approval audit was saved.</p>
       {lastResult.changed_tickets?.map((row,i)=><div key={i}>{row.date} · {row.tier}: {row.previous_result} → {row.result}</div>)}
     </div></div>}
   <div className="split settlement-review-layout">
    <section className="panel"><header className="panel-head"><div><h2>Unresolved fixture queue</h2><p>Country and original SportyBet identity, never guessed from team names</p></div></header>
      <div className="settlement-review-search"><input value={filter} onChange={e=>setFilter(e.target.value)}
         placeholder="Filter team, league, country, event or date" aria-label="Filter pending fixtures"/>
       <span>{results.length} displayed</span></div>
      {q.isPending?<div className="loading" role="status"><Loader2 className="spin" size={18}/> Loading unresolved events…</div>:
        results.length?<div className="settlement-review-scroll">{results.slice(0,500).map((row,i)=>
          <button type="button" key={i} className={'settlement-review-row '+(selected?.event_id===row.event_id&&selected.tier===row.tier?'selected':'')}
            disabled={!!busy} onClick={()=>choose(row)}>
           <span><b>{nice(row.home)} vs {nice(row.away)}</b><small>{row.date} · {row.tier} · {nice(row.country)} · {nice(row.league)}</small>
           <small>{row.event_id} · {why(row.review_category)}</small></span>
           {row.overdue_48h&&<span className="settlement-review-overdue">48h+</span>}
          </button>)}</div>:<div className="empty">No pending fixtures match this filter.</div>}
    </section>
    <section className="panel"><header className="panel-head"><div><h2>Independent final-score review</h2>
      <p>Two deliberate steps; proposal first, explicit approval second</p></div></header>
      {selected?<div className="settlement-review-form">
        <div className="settlement-review-identity"><b>{selected.home} vs {selected.away}</b>
         <small>{selected.date} · {selected.tier} · {selected.event_id}</small>
         <small>{selected.kickoff||'Kickoff not recorded'} · {selected.league||'Unmapped competition'}</small>
        </div>
        <form onSubmit={e=>void propose(e)} className="editor">
         <fieldset disabled={!!busy||!!proposal}>
           <div className="settlement-review-score">
            <label>90-minute home goals<input type="number" min="0" max="30" value={homeScore} onChange={e=>setHomeScore(e.target.value)} required/></label>
            <label>90-minute away goals<input type="number" min="0" max="30" value={awayScore} onChange={e=>setAwayScore(e.target.value)} required/></label>
           </div>
           <label>Official league, federation or club result URL<input type="url" value={url} onChange={e=>setUrl(e.target.value)}
              placeholder="https://official-source.example/match" required/></label>
           <label>What did you independently verify?<textarea rows={4} minLength={45} maxLength={1000} value={note}
              onChange={e=>setNote(e.target.value)} placeholder="Describe the official result page, fixture identity, and the regulation-time score." required/></label>
           <div className="notice warning"><AlertTriangle size={17}/><div>Do not use extra-time, penalties, or an unconfirmed live score. The URL is saved for audit; BetSightly does not automatically authenticate the contents of the page.</div></div>
           <div className="toolbar"><button className="button secondary" type="submit" disabled={!!proposal||!!busy}>{busy==='propose'?<Loader2 className="spin" size={16}/>:<FileIcon/>} Propose evidence — no grading</button></div>
         </fieldset>
        </form>
        {proposal&&<div className="settlement-review-approval">
         <h3>Step 2 · Confirm official final</h3>
         <div className="notice info"><ShieldCheck size={17}/><div><strong>{proposal.score_90.home} – {proposal.score_90.away}</strong>
           <p>{proposal.fixture.home} vs {proposal.fixture.away}</p>
           <a href={proposal.evidence_url} target="_blank" rel="noopener noreferrer">Open official evidence <ExternalLink size={13}/></a>
         </div></div>
         <label>Repeat exact SportyBet event ID<input value={confirmation} onChange={e=>setConfirmation(e.target.value)}
           placeholder={selected.event_id}/></label>
         <label className="check"><input type="checkbox" checked={attested} onChange={e=>setAttested(e.target.checked)}/>
           I checked the official report. This is the 90-minute score for this exact fixture, excluding extra time and penalties.</label>
         <div className="toolbar"><button className="button primary" disabled={!!busy||!attested||confirmation!==selected.event_id}
           onClick={()=>void approve()}>{busy==='approve'?<Loader2 className="spin" size={16}/>:<ShieldCheck size={16}/>} Approve & settle exact event</button>
          <button className="button secondary" disabled={!!busy} onClick={()=>setProposal(null)}>Cancel</button></div>
        </div>}
       </div>:<div className="empty">Choose a saved unresolved fixture to review its exact identity before entering evidence.</div>}
    </section>
   </div>
 </div>;
}

function FileIcon(){return <ClipboardCheck size={16}/>;}
