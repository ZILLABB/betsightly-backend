import React, {useEffect, useMemo, useRef, useState} from 'react';
import {
  Activity, ArrowRight, BarChart3, CheckCircle2,
  ChevronRight, CornerDownLeft, Eye, FileCheck2, Fingerprint,
  Gauge, LayoutDashboard, LockKeyhole, Search, ShieldCheck, Sparkles,
  TrendingUp, Users, type LucideIcon
} from 'lucide-react';

/** An accessible, dependency-free command interface inspired by 21st.dev's dashboard patterns. */
export type CommandItem = {id:string;label:string;group:string};
export function AdminCommandPalette({open,onClose,items,onSelect}:{
  open:boolean;onClose:()=>void;items:CommandItem[];onSelect:(id:string)=>void;
}) {
  const [search,setSearch]=useState(''),[selected,setSelected]=useState(0);
  const field=useRef<HTMLInputElement>(null);
  const matches=useMemo(()=>items.filter(item=>(item.label+' '+item.group).toLowerCase().includes(search.trim().toLowerCase())),[items,search]);
  useEffect(()=>{if(open){setSearch('');setSelected(0);field.current?.focus()}},[open]);
  useEffect(()=>{setSelected(0)},[search]);
  useEffect(()=>{
    if(!open)return;
    const previous=document.activeElement as HTMLElement|null;
    const dismiss=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();onClose()}};
    document.addEventListener('keydown',dismiss);
    return()=>{document.removeEventListener('keydown',dismiss);previous?.focus()};
  },[open,onClose]);
  if(!open)return null;
  const commit=(id:string)=>{onSelect(id);onClose()};
  return <div className="premium-command-layer" onMouseDown={event=>{if(event.target===event.currentTarget)onClose()}}>
    <div className="premium-command-dialog" role="dialog" aria-modal="true" aria-label="Quick navigation">
      <div className="premium-command-search"><Search size={19}/><input ref={field} aria-label="Search admin pages" value={search}
        onChange={event=>setSearch(event.target.value)} placeholder="Search pages, reports, operations…"
        onKeyDown={event=>{if(event.key==='ArrowDown'){event.preventDefault();setSelected(x=>Math.min(Math.max(0,matches.length-1),x+1))}
          if(event.key==='ArrowUp'){event.preventDefault();setSelected(x=>Math.max(0,x-1))}
          if(event.key==='Enter'&&matches[selected]){event.preventDefault();commit(matches[selected].id)}}}/><span className="premium-kbd">ESC</span>
      </div>
      <div className="premium-command-content" role="listbox" aria-label="Available destinations">
        {matches.length ? matches.map((item,i)=><button key={item.id} type="button" className={'premium-command-option '+(i===selected?'chosen':'')}
          role="option" aria-selected={i===selected} onMouseEnter={()=>setSelected(i)} onClick={()=>commit(item.id)}>
          <span className="premium-command-icon"><LayoutDashboard size={16}/></span>
          <span><strong>{item.label}</strong><small>{item.group.toLowerCase()}</small></span>
          {i===selected?<CornerDownLeft size={16}/>:<ChevronRight size={15}/>}
        </button>):<div className="premium-command-empty">No matching page. Try “manual”, “jackpot” or “users”.</div>}
      </div>
      <div className="premium-command-footer"><span><span className="premium-kbd">↑</span><span className="premium-kbd">↓</span> to navigate</span><span><span className="premium-kbd">↵</span> to open</span><span>BetSightly · Admin</span></div>
    </div>
  </div>;
}

const print=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('en-NG'):value==null?'—':String(value);
const validNumber=(value:unknown):number|null=>typeof value==='number'&&Number.isFinite(value)?value:null;
type Journey={key:string;label:string;detail:string;value:number|null;icon:LucideIcon};
export function PremiumOperationsOverview({totals,booking,report,period,loading,onNavigate,onRefresh,refreshing}:{
  totals:Record<string,unknown>;booking:Record<string,unknown>;report:Record<string,unknown>;
  period:number;loading:boolean;onNavigate:(page:string)=>void;onRefresh:()=>void;refreshing:boolean;
}) {
  const visitors=validNumber(totals.visitors);
  const sessions=validNumber(totals.sessions);
  const viewers=validNumber(totals.prediction_viewers);
  const builders=validNumber(totals.builder_users);
  const copiers=validNumber(totals.unique_code_copiers);
  const full=validNumber(booking.full);
  const noCodeRate=validNumber(booking.no_code_rate);
  const cards:Journey[]=[
    {key:'visitors',label:'Visitors',detail:'Unique visitors',value:visitors,icon:Users},
    {key:'sessions',label:'Sessions',detail:'Recorded visits',value:sessions,icon:Activity},
    {key:'predictions',label:'Prediction viewers',detail:'Users who viewed picks',value:viewers,icon:Eye},
    {key:'builder',label:'Builder users',detail:'Users who opened builder',value:builders,icon:BarChart3},
  ];
  // Separate engagement counts, not a sequential funnel or conversion attribution.
  const bars=[{label:'Visitors',value:visitors},{label:'Viewed predictions',value:viewers},
    {label:'Used builder',value:builders},{label:'Copied valid code',value:copiers}];
  const largest=Math.max(1,...bars.map(bar=>bar.value??0));
  const backend=String(report.status||'').toLowerCase();
  const statusKnown=Boolean(report.status);
  const operations=Array.isArray(report.runs)?report.runs:null;
  return <div className="premium-overview">
    <section className="premium-hero" aria-label="BetSightly business overview">
      <div className="premium-hero-grid" aria-hidden="true"/>
      <div className="premium-hero-main"><span className="premium-hero-eyebrow"><Sparkles size={14}/> BETSIGHTLY / OPERATIONS INTELLIGENCE</span>
        <h2>Everything that matters.<br/><em>One command center.</em></h2>
        <p>Live backend evidence for audience growth, bookmaker readiness and editorial publication. Figures below reflect the selected {period===1?'day':period+'-day'} reporting window.</p>
        <div className="premium-hero-actions">
          <button type="button" className="premium-hero-primary" onClick={()=>onNavigate('manual')}><FileCheck2 size={17}/> Open publishing studio <ArrowRight size={15}/></button>
          <button type="button" className="premium-hero-secondary" onClick={()=>onNavigate('jackpot')}><Gauge size={16}/> Private Jackpot</button>
        </div>
      </div>
      <div className="premium-hero-system">
        <div className="premium-system-top"><span className="premium-system-orb"><Activity size={22}/></span><span>SYSTEM OBSERVATION<small>Read from the production API</small></span></div>
        <div className="premium-system-state"><span className={'premium-system-led '+(statusKnown&&['healthy','ok','success','running','active'].includes(backend)?'ok':'unknown')}/><strong>{statusKnown?String(report.status):loading?'Checking…':'Status unavailable'}</strong></div>
        <div className="premium-system-row"><span>Recorded operations</span><strong>{loading?'—':operations?print(operations.length):'Unavailable'}</strong></div>
        <div className="premium-system-row"><span>Last observed run</span><strong>{loading?'—':operations?print(operations[0]?.status):'Unavailable'}</strong></div>
        <button type="button" className="premium-system-update" onClick={onRefresh} disabled={refreshing}>
          <span>{refreshing?'Refreshing snapshot…':'Refresh backend snapshot'}</span> <ArrowRight size={14}/></button>
      </div>
    </section>
    <div className="premium-section-label"><span><span className="premium-eyebrow">PERFORMANCE SNAPSHOT</span><strong>Audience at a glance</strong></span><small>{period===1?'Today':period+' days'} · Server-reported figures</small></div>
    <section className="premium-bento-metrics" aria-label="Audience metrics">
      {cards.map(({key,label,detail,value,icon:Icon},i)=><div className={'premium-metric-tile premium-metric-'+(i+1)} key={key}>
        <div className="premium-metric-top"><span className="premium-metric-icon"><Icon size={18}/></span><span className="premium-metric-index">0{i+1} / LIVE DATA</span></div>
        <strong className="premium-metric-value">{loading?<span className="premium-metric-skeleton"/>:print(value)}</strong>
        <span className="premium-metric-name">{label}</span><span className="premium-metric-detail">{detail}</span>
        <div className="premium-metric-accent" aria-hidden="true"/>
      </div>)}
    </section>
    <div className="premium-bento-secondary">
      <section className="premium-data-panel premium-engagement">
        <header className="premium-data-head"><div><span className="premium-eyebrow">REACH & ENGAGEMENT</span><h3>Audience activity</h3><p>Counts reflect independent recorded actions, not a sequential conversion funnel.</p></div><TrendingUp size={19}/></header>
        <div className="premium-bars">{bars.map((bar,i)=><div key={bar.label} className="premium-bar-item">
          <div className="premium-bar-label"><span>{bar.label}</span><strong>{loading?'—':print(bar.value)}</strong></div>
          <div className="premium-bar-rail" aria-hidden="true"><span style={{width:loading?'0%':String(Math.min(100,100*(bar.value??0)/largest))+'%',transitionDelay:String(i*65)+'ms'}}/></div>
        </div>)}</div>
        <table className="premium-accessible-data"><caption>Exact activity counts for the selected reporting window</caption><tbody>
          {bars.map(row=><tr key={row.label}><th scope="row">{row.label}</th><td>{print(row.value)}</td></tr>)}
        </tbody></table>
      </section>
      <section className="premium-data-panel premium-booking">
        <header className="premium-data-head"><div><span className="premium-eyebrow">BOOKMAKER OPERATIONS</span><h3>Booking intelligence</h3><p>Verified codes are distinct from bets being placed.</p></div><ShieldCheck size={20}/></header>
        <div className="premium-booking-spotlight"><div><span>Full booking codes</span><strong>{loading?'—':print(full)}</strong></div><span className="premium-spotlight-symbol"><Fingerprint size={27}/></span></div>
        <div className="premium-compact-data"><div><span>No-code rate</span><strong>{loading||noCodeRate==null?'—':Math.round(noCodeRate*100)+'%'}</strong></div>
          <div><span>Booking attempts</span><strong>{loading?'—':print(booking.attempts)}</strong></div>
          <div><span>Partially recovered</span><strong>{loading?'—':print(booking.partial)}</strong></div></div>
        <button type="button" className="premium-link-row" onClick={()=>onNavigate('sporty')}>Inspect bookmaker health <ArrowRight size={15}/></button>
      </section>
    </div>
  </div>;
}

/** Confirmation that never implies a mutation has already happened. */
export function AdminActionDialog({open,title,summary,confirmText='Confirm action',busy=false,onCancel,onConfirm}:{
  open:boolean;title:string;summary:string;confirmText?:string;busy?:boolean;onCancel:()=>void;onConfirm:()=>void;
}) {
  const button=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    if(!open)return;
    button.current?.focus();
    const close=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!busy)onCancel()};
    window.addEventListener('keydown',close);
    return()=>window.removeEventListener('keydown',close);
  },[open,busy,onCancel]);
  if(!open)return null;
  return <div className="premium-confirm-layer" onMouseDown={event=>{if(!busy&&event.target===event.currentTarget)onCancel()}}>
    <div className="premium-confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="admin-confirm-title" aria-describedby="admin-confirm-description">
      <span className="premium-confirm-badge"><LockKeyhole size={18}/></span>
      <span className="premium-eyebrow">REVIEW BEFORE CONTINUING</span><h2 id="admin-confirm-title">{title}</h2><p id="admin-confirm-description">{summary}</p>
      <div className="premium-confirm-policy"><ShieldCheck size={16}/> The action still requires backend verification. No server change has been made by opening this dialog.</div>
      <div className="premium-confirm-actions"><button ref={button} type="button" className="button secondary" onClick={onCancel} disabled={busy}>Cancel</button><button type="button" className="button primary" disabled={busy} onClick={onConfirm}>{busy?'Processing…':confirmText} <ArrowRight size={16}/></button></div>
    </div>
  </div>;
}
