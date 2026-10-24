import React, {useEffect, useMemo, useRef, useState} from 'react';
import {useIsFetching, useQuery, useQueryClient} from '@tanstack/react-query';
import {
 Activity, BarChart3, CheckCircle2, ChevronRight, Clock3, Database, FileCheck2,
 Globe2, LayoutDashboard, Loader2, LockKeyhole, LogOut, Megaphone, Menu, PanelLeftClose, PanelLeftOpen, Search, RefreshCcw,
 Send, Settings2, ShieldCheck, Ticket, UploadCloud, Users, X, AlertTriangle, type LucideIcon
} from 'lucide-react';
import {api, ApiError, isAmbiguous, tiers} from './api';
import Insights from './Insights';
import PrivateJackpot from './PrivateJackpot';
import {AdminActionDialog, AdminCommandPalette, PremiumOperationsOverview} from './PremiumComponents';

type Page = 'overview' | 'audience' | 'predictions' | 'analytics-health' | 'manual' | 'jackpot' | 'sporty' | 'readiness' | 'content' | 'campaign' | 'publishing' | 'referrals' | 'settings';
const nav: {id: Page; label: string; icon: LucideIcon; group: string}[] = [
 {id:'overview',label:'Overview',icon:LayoutDashboard,group:'COMMAND CENTER'},
 {id:'audience',label:'Users & retention',icon:Users,group:'COMMAND CENTER'},
 {id:'predictions',label:'Predictions & builder',icon:BarChart3,group:'COMMAND CENTER'},
 {id:'analytics-health',label:'Analytics health',icon:Activity,group:'COMMAND CENTER'},
 {id:'manual',label:'Manual SportyBet',icon:Ticket,group:'COMMAND CENTER'},
 {id:'jackpot',label:'Private Jackpot',icon:Ticket,group:'COMMAND CENTER'},
 {id:'sporty',label:'Booking health',icon:Activity,group:'COMMAND CENTER'},
 {id:'readiness',label:'Market readiness',icon:Database,group:'COMMAND CENTER'},
 {id:'content',label:'Content',icon:Megaphone,group:'OPERATIONS'},
 {id:'campaign',label:'Homepage campaign',icon:Globe2,group:'OPERATIONS'},
 {id:'publishing',label:'Publishing',icon:Send,group:'OPERATIONS'},
 {id:'referrals',label:'Referrals',icon:Users,group:'OPERATIONS'},
 {id:'settings',label:'Settings',icon:Settings2,group:'OPERATIONS'}
];
const n = (x: unknown) => typeof x === 'number' ? x.toLocaleString() : (x == null ? '—' : String(x));
const errText = (error: unknown) => error instanceof Error ? error.message : 'Unexpected error';
function Loading({label='Retrieving verified data…'}:{label?:string}) {return <div className="loading loading-rich" role="status" aria-live="polite"><Loader2 size={19} className="spin"/><div><strong>{label}</strong><span>Waiting for the connected service · no result has been confirmed yet</span></div></div>;}
function MetricsSkeleton() {return <div className="metric-grid" role="status" aria-label="Loading analytics metrics">{Array.from({length:6},(_,i)=><div className="metric metric-skeleton" key={i} aria-hidden="true"><span className="skeleton-line short"/><strong className="skeleton-line value"/><small className="skeleton-line medium"/></div>)}</div>;}
function Warning({children}:{children:React.ReactNode}) {return <div className="notice warning" role="alert"><AlertTriangle size={17}/><div>{children}</div></div>;}
function Info({children}:{children:React.ReactNode}) {return <div className="notice info" role="note"><ShieldCheck size={17}/><div>{children}</div></div>;}
function Empty({text='No records for the selected period.'}:{text?:string}) {return <div className="empty">{text}</div>;}
function DataError({error, retry}:{error:unknown;retry:()=>void}) {return <div className="notice error" role="alert"><AlertTriangle size={17}/><div><strong>Unable to load verified data.</strong><p>{errText(error)}</p><button type="button" className="mini-button" onClick={retry}><RefreshCcw size={14}/> Retry request</button></div></div>;}
function Panel({title,subtitle,children,action}:{title:string;subtitle?:string;children:React.ReactNode;action?:React.ReactNode}) {
 return <section className="panel"><header className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</header>{children}</section>;
}
function Metric({label,value,detail}:{label:string;value:unknown;detail?:string}) {
 return <div className="metric"><span>{label}</span><strong>{n(value)}</strong><small>{detail || 'Live operational data'}</small></div>;
}
function ResultNote({kind,text}:{kind:'error'|'success'|'info';text:string}) {
 return <div role={kind==='error'?'alert':'status'} className={'notice ' + kind}>{kind==='success'?<CheckCircle2 size={18}/>:kind==='error'?<AlertTriangle size={18}/>:<Clock3 size={18}/>}<div>{text}</div></div>;
}

function Overview({onNavigate}:{onNavigate:(page:Page)=>void}) {
 const [days,setDays]=useState(1);
 const q=useQuery({queryKey:['analytics',days],queryFn:()=>api<any>('analytics?days='+days)});
 const status=useQuery({queryKey:['growth-status'],queryFn:()=>api<any>('status')});
 const summary=q.data?.summary||{}, totals=summary.totals||{}, booking=summary.booking||{}, report=status.data||{};
 const refresh=()=>{void q.refetch();void status.refetch();};
 return <>
  <div className="page-heading premium-overview-heading"><div><span className="eyebrow">PRIVATE WORKSPACE / LIVE OPERATIONS</span><h1>Command overview.</h1><p>Monitor the operation, identify friction and move from evidence to action.</p></div>
   <div className="premium-period-switch" role="group" aria-label="Reporting period">{[1,7,30].map(x=><button type="button" key={x} className={days===x?'active':''} aria-pressed={days===x} onClick={()=>setDays(x)}>{x===1?'Today':x+' days'}</button>)}</div></div>
  {(q.isError||status.isError)&&<DataError error={q.error||status.error} retry={refresh}/>}
  <PremiumOperationsOverview totals={totals} booking={booking} report={report} period={days} loading={q.isPending&&!q.data}
    refreshing={q.isFetching||status.isFetching} onRefresh={refresh} onNavigate={id=>onNavigate(id as Page)}/>
  <Info>Dashboard metrics are observed backend records, not estimated bets or guaranteed outcomes. Model scoring, manual publications and bookmaker verification remain separate.</Info>
 </>;
}

type ManualRequest={tier:string;lines:string;replace_official_display:boolean};
type Imported={code:string;tier:string;lines:string;original_leg_count:number;unresolved_count?:number;status?:string;games?:any[];warnings?:string[];converted_features?:any[];total_odds?:number};
function ManualStudio() {
 const qc=useQueryClient();
 const [tier,setTier]=useState<string>('2_odds'),[code,setCode]=useState(''),[lines,setLines]=useState(''),[convert,setConvert]=useState(false);
 const [replace,setReplace]=useState(false),[imported,setImported]=useState<Imported|null>(null),[preview,setPreview]=useState<{request:ManualRequest;data:any}|null>(null);
 const [stage,setStage]=useState(0),[busy,setBusy]=useState(''),[note,setNote]=useState<{kind:'error'|'success'|'info';text:string}|null>(null);
 const [publishReview,setPublishReview]=useState(false);
 const [uncertain,setUncertain]=useState(!!sessionStorage.getItem('bs_admin_uncertain'));
 const [review,setReview]=useState<Record<number,string>>({});
 const operationLatch=useRef(false);
 const current=useQuery({queryKey:['manual-tiers'],queryFn:()=>api<any>('manual-tiers'),refetchOnMount:'always'});
 const saved=current.data?.published||{};
 const normalized=lines.trim().replace(/\r\n/g,'\n');
 const request=useMemo<ManualRequest>(()=>({tier,lines:normalized,replace_official_display:replace}),[tier,normalized,replace]);
 const ready=!!preview && JSON.stringify(preview.request)===JSON.stringify(request);
 const importedExact=!!imported && imported.code===code.trim() && imported.tier===tier && imported.lines.trim()===normalized && !convert && !imported.unresolved_count && !imported.converted_features?.length && imported.status==='IMPORTED_NOT_PUBLISHED';
 const active=!!busy;
 const edit=()=>{setPreview(null);setNote(null);setStage(0);};
 const run=async(name:string,fn:()=>Promise<void>)=>{if(operationLatch.current)return;operationLatch.current=true;setBusy(name);try{await fn()}catch(e){setNote({kind:'error',text:errText(e)});}finally{operationLatch.current=false;setBusy('')}};
 const refresh=async()=>{const r=await current.refetch();if(!r.isError && r.data && uncertain){
   const pendingRaw=sessionStorage.getItem('bs_admin_uncertain')||'';
   let pending:{tier:string;previousCode:string}={tier:pendingRaw||tier,previousCode:''};
   try{pending=JSON.parse(pendingRaw)}catch{}
   const record=r.data.published?.[pending.tier||tier];
   if(record?.share_code && record.share_code!==pending.previousCode){setUncertain(false);sessionStorage.removeItem('bs_admin_uncertain');setNote({kind:'success',text:'New saved '+(pending.tier||tier)+' ticket confirmed: '+record.share_code+'. Do not publish it again.'});}
   else setNote({kind:'info',text:'Saved tickets refreshed. No matching ticket confirmed. Do not repeat an interrupted publication without reconciling the original request.'});
  }};
 const importFile=async(event:React.ChangeEvent<HTMLInputElement>)=>{
  const file=event.target.files?.[0];event.target.value='';if(!file)return;
  await run('Importing CSV file',async()=>{
   if(file.size>16000)throw Error('CSV file exceeds the 16 KB limit. No selections changed.');
   const content=(await file.text()).replace(/\r\n/g,'\n').trim();
   if(content.length>6000)throw Error('CSV exceeds 6,000 characters. Split the file; no games will be silently truncated.');
   if(!content)throw Error('This CSV contains no selections.');
   const count=content.split('\n').filter(Boolean).length;
   setLines(content);setImported(null);setPreview(null);setStage(2);
   setNote({kind:'info',text:count+' rows loaded from CSV. Review every selection, then run Check live prices. Nothing has been published.'});
  });
 };
 const importCode=()=>run('Reading SportyBet code',async()=>{
  if(code.trim().length<4)throw Error('Enter a valid SportyBet booking code.');
  setStage(1);setPreview(null);setImported(null);
  const res=await api<Imported>('manual-tiers/import-code',{tier,code:code.trim(),convert_special:convert});
  if((res.original_leg_count||0)<1 || !Array.isArray(res.games))throw Error('SportyBet did not return a complete selection list. No rows changed.');
  setImported({...res,code:code.trim()});
  setReview({});
  if(res.unresolved_count || res.status==='NEEDS_MANUAL_REVIEW'){
   setNote({kind:'info',text:String(res.unresolved_count||0)+' special/unmapped selections need your explicit review. Nothing has been published.'});
  }else{
   const next=(res.lines||'').trim().replace(/\r\n/g,'\n');
   if(next.split('\n').filter(Boolean).length !== res.original_leg_count)throw Error('Import leg count mismatch. No partial import allowed.');
   setLines(next);setNote({kind:'success',text:res.original_leg_count+' games imported. Review every market and then check live prices. No code published.'});
  }
  setStage(2);
 });
 const applyReview=()=>{
  if(!imported?.games?.length)return;
  const rows=imported.games.map((g:any,i:number)=>{
   const market=g.requires_review?review[i]:g.market;
   return String(g.sportybet_event_id||'')+','+String(market||'');
  });
  if(rows.some(x=>x.startsWith(',') || x.endsWith(',')) || rows.length!==imported.original_leg_count){setNote({kind:'error',text:'Choose a regular market for every unresolved leg. No selections can be dropped.'});return;}
  setLines(rows.join('\n'));setImported({...imported,lines:rows.join('\n'),unresolved_count:0,status:'REVIEWED_MANUALLY'});
  setNote({kind:'info',text:'Reviewed rows applied. This is a different market selection; check live prices before publication.'});setPreview(null);
 };
 const check=()=>run('Checking live SportyBet prices',async()=>{
  if(!normalized)throw Error('Import a code or enter event ID,market rows first.');
  if(imported?.unresolved_count)throw Error('Resolve all imported special markets before preview.');
  const result=await api<any>('manual-tiers/preview',request);
  if(!Array.isArray(result.games)||!result.games.length||result.games.length!==normalized.split('\n').filter(Boolean).length)throw Error('Live preview did not verify every selection.');
  setPreview({request,data:result});setStage(3);
  setNote({kind:'success',text:'Live preview confirmed '+result.games.length+' legs at '+result.total_odds+'x. No ticket published yet.'});
 });
 const publish=()=>run('Publishing verified ticket',async()=>{
  if(!ready || !preview)throw Error('Recheck live prices after every change before publishing.');
  if(uncertain)throw Error('Earlier publication outcome uncertain. Check saved tickets before any new POST.');
  // The review dialog requires explicit confirmation before this mutation.
  const previousCode=String(saved[tier]?.share_code||'');
  setStage(4);sessionStorage.setItem('bs_admin_uncertain',JSON.stringify({tier,previousCode}));
  try{
   const path=importedExact?'manual-tiers/publish-imported':'manual-tiers/publish';
   const payload=importedExact?{tier,code:code.trim(),replace_official_display:replace}:request;
   const result=await api<any>(path,payload);
   const checkResult=await current.refetch();
   const persisted=checkResult.data?.published?.[tier];
   if(persisted?.share_code && persisted.share_code===result.share_code){
    sessionStorage.removeItem('bs_admin_uncertain');setUncertain(false);setStage(5);setPreview(null);setImported(null);
    setNote({kind:'success',text:'Published, saved and verified: '+result.share_code+' · '+n(persisted.leg_count)+' legs · '+n(persisted.total_odds)+'x. Model calibration remains separate.'});
    qc.invalidateQueries({queryKey:['analytics']});
   }else{
    setUncertain(true);setNote({kind:'error',text:'SportyBet returned '+n(result.share_code)+' but DB read-back has not confirmed that exact code. Do NOT submit the same ticket twice.'});
   }
  }catch(error){
   if(!isAmbiguous(error)){
    sessionStorage.removeItem('bs_admin_uncertain');setUncertain(false);setStage(3);
    setNote({kind:'error',text:'Backend rejected the ticket: '+errText(error)+'. Nothing was confirmed as published; correct the issue and recheck prices.'});return;
   }
   setUncertain(true);await current.refetch().catch(()=>null);
   const snapshot=qc.getQueryData<any>(['manual-tiers']);
   const existing=snapshot?.published?.[tier];
   const newTicket=!!existing?.share_code && existing.share_code!==previousCode;
   setNote({kind:'error',text:newTicket && isAmbiguous(error) ?
    'Request interrupted; saved '+tier+' ticket detected: '+existing.share_code+'. Verify saved ticket before any other action.' :
    'Publication outcome not confirmed: '+errText(error)+'. Do NOT send another POST. Check saved tickets and reconcile the result.'});
   if(newTicket){setUncertain(false);sessionStorage.removeItem('bs_admin_uncertain');}
  }
 });
 const tierChange=(v:string)=>{setTier(v);setImported(null);edit();setReplace(false)};
 const codeChange=(v:string)=>{setCode(v);setImported(null);edit()};
 const lineChange=(v:string)=>{setLines(v);setImported(null);edit()};
 const marketOptions=['home_win','away_win','draw','home_or_draw','away_or_draw','home_or_away','over_0_5','over_1_5','over_2_5','over_3_5','over_4_5','btts_yes'];
 return <>
  <div className="page-heading"><div><span className="eyebrow">BOOKMAKER-VERIFIED</span><h1>Manual Publishing Studio.</h1><p>Import, review, live-price and confirm every selection — never guess whether a publish worked.</p></div><button className="mini-button" disabled={active} onClick={()=>run('Refreshing saved tickets',refresh)}><RefreshCcw size={16}/> Refresh saved</button></div>
  <Panel title="Publication progress" subtitle="Server-confirmed steps only">
   <div className="workflow-header" role="status" aria-live="polite"><div><span className="workflow-kicker">CURRENT OPERATION</span><strong>{uncertain?'Action needed: reconcile the last publication':busy||(['Ready to import or enter picks','Reading SportyBet selections','Review the exact market choices','Prices verified · awaiting your approval','Publishing · awaiting saved result','Published and confirmed'][stage]||'Review ticket')}</strong></div><span className={'workflow-stage '+(uncertain?'attention':stage===5?'complete':'')}>{stage===0?'Not started':stage===5?'5/5 saved':'Step '+stage+' of 5'}</span></div>
   <div className="steps" aria-label="Manual ticket publication stages">{['Read code','Review markets','Verify prices','Publish','Confirm saved'].map((x,i)=><div key={x} className={'step '+(stage===i+1&&stage!==5?'current':stage>i?'done':'')}><span>{stage>i?<CheckCircle2 size={16}/>:i+1}</span>{x}</div>)}</div>
   {active&&<div className="operation-signal" role="status" aria-live="polite"><div className="operation-spinner"><Loader2 className="spin" size={19}/></div><div><strong>{busy}…</strong><span>Request in progress. Controls are locked; wait for the server response and saved-record confirmation. Never retry an uncertain publication.</span></div></div>}
   {uncertain&&<Warning>An earlier manual publishing response was interrupted. Duplicate publishing is blocked until the saved record is reconciled.</Warning>}
   {note&&<ResultNote kind={note.kind} text={note.text}/>}
  </Panel>
  <div className="split manual-layout">
   <Panel title="Ticket editor" subtitle="Original model selections and calibration are never overwritten">
    <fieldset disabled={active} aria-busy={active} className="editor">
     <label>Destination tier<select value={tier} onChange={e=>tierChange(e.target.value)}>{tiers.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
     {tier==='rollover'&&<div className="notice info">Rollover eligibility is determined by the backend. An unsettled day cannot be bypassed. {current.data?.rollover?.message||''}</div>}
     <label>SportyBet booking code<div className="input-action"><input value={code} onChange={e=>codeChange(e.target.value)} placeholder="Paste booking code"/><button className="button secondary" onClick={importCode} type="button">{busy==='Reading SportyBet code'?<Loader2 size={16} className="spin"/>:<UploadCloud size={16}/>} {busy==='Reading SportyBet code'?'Reading code…':'Read code'}</button></div></label>
     <label className="check"><input type="checkbox" checked={convert} onChange={e=>{setConvert(e.target.checked);setImported(null);edit()}}/>Convert early-goal/1UP/2UP specials to ordinary markets (changes the wager)</label>
     {imported?.warnings?.length ? <Warning>{imported.warnings.join(' · ')}</Warning>:null}
     {!!imported?.converted_features?.length&&<Warning>{imported.converted_features.length} special markets were converted. Early payouts and bonuses are not preserved.</Warning>}
     {!!imported?.unresolved_count&&<div className="review-box"><h3>Manual market mapping required</h3><p>Review the original betslip. Select the correct regular market for every unresolved event; no silent substitutions.</p>{(imported.games||[]).map((g:any,i:number)=>g.requires_review?<label key={i}>{n(g.sportybet_event_id)} · {n(g.reported_market)}<select value={review[i]||''} onChange={e=>setReview(v=>({...v,[i]:e.target.value}))}><option value="">Choose a market…</option>{marketOptions.map(x=><option key={x}>{x}</option>)}</select></label>:null)}<button className="button secondary" type="button" onClick={applyReview}>Apply reviewed choices</button></div>}
     <label>Event ID,market — one per line<textarea rows={10} spellCheck={false} value={lines} onChange={e=>lineChange(e.target.value)} placeholder={'52587,home_win\n17187,over_1_5'}/></label>
     <label className="file-import">Import CSV or TXT (16 KB maximum)<input type="file" accept=".csv,.txt,text/csv,text/plain" onChange={importFile}/></label>
     {['2_odds','5_odds','10_odds','over_1_5'].includes(tier)&&<label className="check"><input type="checkbox" checked={replace} onChange={e=>{setReplace(e.target.checked);edit()}}/>Replace the PUBLIC display for this tier; preserve the original model result</label>}
     <div className="toolbar"><button type="button" className="button secondary" onClick={check} disabled={!!imported?.unresolved_count||!normalized}>{busy==='Checking live SportyBet prices'?<Loader2 size={16} className="spin"/>:<FileCheck2 size={16}/>} {busy==='Checking live SportyBet prices'?'Checking every price…':'Check live prices'}</button><button type="button" className="button primary" disabled={!ready||uncertain} onClick={()=>setPublishReview(true)}>{busy==='Publishing verified ticket'?<Loader2 size={16} className="spin"/>:<Send size={16}/>} {busy==='Publishing verified ticket'?'Publishing and confirming…':'Publish verified ticket'}</button></div>
     {ready&&Number(preview?.data?.settlement_source_coverage?.unmapped||0)>0&&<Warning>
      <strong>Final-score verification coverage warning:</strong> {n(preview?.data?.settlement_source_coverage?.unmapped)} of {n(preview?.data?.games?.length)} fixtures lack a verified ESPN competition mapping. A bookmaker code may still be valid, but those results could remain unverified after full time. Unsupported competitions are not automatically marked won, lost or void.
      {(preview?.data?.settlement_source_warnings||[]).slice(0,8).map((warning:any,i:number)=><div key={i}>{n(warning.fixture)} · {n(warning.league)}</div>)}
     </Warning>}
     {ready&&<div className="notice success" role="status"><CheckCircle2 size={17}/><div><strong>Ready for your confirmation</strong><p>{n(preview?.data?.games?.length)} exact games verified at {n(preview?.data?.total_odds)}x. A fresh bookmaker code is issued only after confirmation and saved readback.</p></div></div>}
    </fieldset>
   </Panel>
   <div className="panel-stack">
    <Panel title="Live preview" subtitle="Prices are checked against the actual market">
     {preview?.data?.games?.length?<div className="scroll-table"><table><thead><tr><th>Fixture</th><th>Market</th><th>Odds</th></tr></thead><tbody>{preview.data.games.map((g:any,i:number)=><tr key={i}><td>{g.home_team} – {g.away_team}</td><td>{g.market}</td><td>{n(g.odds)}x</td></tr>)}</tbody></table></div>:<Empty text="Import a code and choose Check live prices. No predictions are being published yet."/>}
    </Panel>
    <Panel title="Today's saved editorial tickets" subtitle="Read directly from the database" action={<button className="mini-button" onClick={()=>current.refetch()} disabled={active}><RefreshCcw size={14}/></button>}>
     {current.isPending?<Loading/>:current.isError?<DataError error={current.error} retry={()=>current.refetch()}/>:Object.keys(saved).length?<div className="saved-cards">{Object.entries(saved).map(([key,value])=>{const v=value as any;return <div key={key} className="saved-card"><div><b>{tiers.find(x=>x[0]===key)?.[1]||key}</b><small>{n(v.leg_count)} legs · {n(v.total_odds)}x</small></div><strong>{v.share_code||'No verified code'}</strong></div>})}</div>:<Empty text="No saved manual tickets for today."/>}
    </Panel>
   </div>
  </div>
  <AdminActionDialog open={publishReview} title="Publish this verified ticket?"
    summary={String(preview?.data?.games?.length||0)+' exact selections for '+tier+' at '+n(preview?.data?.total_odds)+'x. This may create a new SportyBet code. Original model results remain separate, and the saved result must be verified.'+(Number(preview?.data?.settlement_source_coverage?.unmapped||0)>0?' IMPORTANT: '+n(preview?.data?.settlement_source_coverage?.unmapped)+' fixture(s) lack verified score-source coverage, so settlement may be delayed.':'')}
    confirmText="Publish and verify" busy={active} onCancel={()=>setPublishReview(false)} onConfirm={()=>{setPublishReview(false);void publish();}}/>
 </>;
}

function Operations({mode}:{mode:'sporty'|'readiness'}) {
 const analytics=useQuery({queryKey:['analytics',1],queryFn:()=>api<any>('analytics?days=1'),enabled:mode==='sporty'});
 const ready=useQuery({queryKey:['market-readiness'],queryFn:()=>api<any>('market-readiness'),enabled:mode==='readiness'});
 const data=mode==='sporty'?analytics.data?.summary:ready.data;
 const booking=data?.booking||{},sporty=data?.sportybet||{};
 return <>
  <div className="page-heading"><div><span className="eyebrow">OPERATIONAL EVIDENCE</span><h1>{mode==='sporty'?'SportyBet health.':'Market readiness.'}</h1><p>{mode==='sporty'?'Code generation, readback and fixture coverage.':'Provider coverage, market visibility and reasons picks cannot be published.'}</p></div><button className="mini-button" onClick={()=>mode==='sporty'?analytics.refetch():ready.refetch()}><RefreshCcw size={15}/> Refresh</button></div>
  {(analytics.isPending&&mode==='sporty')||(ready.isPending&&mode==='readiness')?<Loading/>:null}
  {(analytics.error&&mode==='sporty')||(ready.error&&mode==='readiness')?<DataError error={analytics.error||ready.error} retry={()=>{analytics.refetch();ready.refetch()}}/>:null}
  {mode==='sporty'&&<><div className="metric-grid"><Metric label="Attempts" value={booking.attempts}/><Metric label="Full codes" value={booking.full}/><Metric label="Partial" value={booking.partial}/><Metric label="Bookmaker matches" value={sporty.unique_indexed_fixtures??sporty.fixtures}/></div><Panel title="Source coverage" subtitle="Absence of evidence must never be labelled healthy"><div className="data-rows">{Object.entries(sporty).filter(([k])=>!['error'].includes(k)).slice(0,16).map(([key,value])=><div key={key}><span>{key.replaceAll('_',' ')}</span><b>{typeof value==='object'?JSON.stringify(value):n(value)}</b></div>)}</div>{sporty.error&&<Warning>{String(sporty.error)}</Warning>}</Panel></>}
  {mode==='readiness'&&<Panel title="Live source evidence" subtitle="Detailed backend response; no fabricated figures">{data?<pre className="json-dump">{JSON.stringify(data,null,2)}</pre>:<Empty/>}</Panel>}
 </>;
}


type HomeCampaign={
 enabled:boolean;reviewed:boolean;eyebrow:string;headline:string;description:string;
 cta_text:string;cta_path:string;starts_on:string;ends_on:string;source_url:string
};
function CampaignEditor(){
 const qc=useQueryClient();
 const q=useQuery({queryKey:['homepage-campaign'],queryFn:()=>api<{campaign:HomeCampaign}>('homepage-campaign')});
 const [draft,setDraft]=useState<HomeCampaign|null>(null),[busy,setBusy]=useState(false),[feedback,setFeedback]=useState('');
 useEffect(()=>{if(q.data?.campaign)setDraft({...q.data.campaign})},[q.data]);
 const edit=(field:keyof HomeCampaign,value:string|boolean)=>setDraft(current=>current?{...current,[field]:value}:current);
 const save=async()=>{
   if(!draft||busy)return;
   if(draft.enabled && !window.confirm('Publish this verified time-bounded hero campaign to the public website? The event, source and dates must be fact-checked.'))return;
   setBusy(true);setFeedback('');
   try{await api('homepage-campaign',draft,'POST');setFeedback('Campaign saved. The public website will display it only within the approved dates.');await qc.invalidateQueries({queryKey:['homepage-campaign']});}
   catch(e){setFeedback(errText(e))}finally{setBusy(false)}
 };
 return <>
  <div className="page-heading"><div><span className="eyebrow">WEBSITE EDITORIAL</span><h1>Matchday homepage.</h1><p>Show verified Champions League, World Cup or league-week campaigns, with automatic expiration.</p></div></div>
  {q.isPending?<Loading/>:q.isError?<DataError error={q.error} retry={()=>q.refetch()}/>:draft?<div className="split">
  <Panel title="Campaign configuration" subtitle="Only approved events, dated and sourced, may appear on the public hero">
   <div className="editor">
    <label>Eyebrow (50 characters)<input maxLength={50} value={draft.eyebrow} onChange={e=>edit('eyebrow',e.target.value)}/></label>
    <label>Headline (85 characters)<input maxLength={85} value={draft.headline} onChange={e=>edit('headline',e.target.value)}/></label>
    <label>Description (220 characters)<textarea rows={3} maxLength={220} value={draft.description} onChange={e=>edit('description',e.target.value)}/></label>
    <div className="split"><label className="setting-line">CTA text<input maxLength={36} value={draft.cta_text} onChange={e=>edit('cta_text',e.target.value)}/></label><label className="setting-line">CTA destination<select value={draft.cta_path} onChange={e=>edit('cta_path',e.target.value)}>{['/predictions','/build-slip','/results','/rollover'].map(x=><option key={x}>{x}</option>)}</select></label></div>
    <div className="split"><label className="setting-line">Start date<input type="date" value={draft.starts_on} onChange={e=>edit('starts_on',e.target.value)}/></label><label className="setting-line">End date<input type="date" value={draft.ends_on} onChange={e=>edit('ends_on',e.target.value)}/></label></div>
    <label>Public HTTPS source URL<input type="url" placeholder="https://..." maxLength={350} value={draft.source_url} onChange={e=>edit('source_url',e.target.value)}/></label>
    <label className="check"><input type="checkbox" checked={draft.reviewed} onChange={e=>edit('reviewed',e.target.checked)}/>I have verified the event, source and date range.</label>
    <label className="check"><input type="checkbox" checked={draft.enabled} onChange={e=>edit('enabled',e.target.checked)}/>Enable public homepage campaign for the scheduled dates</label>
    <div className="toolbar"><button className="button primary" onClick={save} disabled={busy}>{busy?<Loader2 size={16} className="spin"/>:<CheckCircle2 size={16}/>} Save campaign</button><button className="button secondary" disabled={busy} onClick={()=>setDraft({...q.data!.campaign})}>Discard changes</button></div>
    {feedback&&<ResultNote kind={feedback.startsWith('Campaign saved')?'success':'error'} text={feedback}/>}
   </div>
  </Panel>
  <Panel title="Editorial preview" subtitle="Content preview, not a published claim">
   <div className="campaign-preview"><span className="eyebrow">{draft.eyebrow||'MATCHDAY CAMPAIGN'}</span><h3>{draft.headline||'Your verified headline will appear here.'}</h3><p>{draft.description||'Explain what is happening this week, without promising winning bets.'}</p><span className="button secondary">{draft.cta_text||'View predictions'} <ChevronRight size={15}/></span></div>
   <div className="data-rows"><div><span>Publication status</span><b>{draft.enabled?'Scheduled (pending validation)':'Disabled'}</b></div><div><span>Fact check</span><b>{draft.reviewed?'Reviewed':'Not reviewed'}</b></div><div><span>Source link</span><b>{draft.source_url?'Provided':'Missing'}</b></div><div><span>Active dates</span><b>{draft.starts_on||'—'} → {draft.ends_on||'—'}</b></div></div>
   <Info>Homepage campaigns are independent of prediction results, betting success and calibration. Expired campaigns disappear automatically.</Info>
  </Panel></div>:null}
 </>;
}

function Content() {
 const qc=useQueryClient();
 const q=useQuery({queryKey:['content'],queryFn:()=>api<any>('content?limit=150')});
 const [active,setActive]=useState<number|null>(null),[generating,setGenerating]=useState<'drafts'|'publish'|null>(null);
 const [selected,setSelected]=useState<any>(null),[message,setMessage]=useState('');
 const act=async(id:number,operation:'approve'|'publish')=>{
  if(active!==null||generating)return;
  if(operation==='publish'&&!window.confirm('Publish this approved content now?'))return;
  setActive(id);setMessage('');
  try{await api('content/'+id+'/'+operation,{},'POST');setMessage('Action acknowledged by the backend; verify delivery status in Publishing.');await qc.invalidateQueries({queryKey:['content']});}
  catch(e){setMessage(errText(e));}finally{setActive(null)}
 };
 const generate=async(publish:boolean)=>{
  if(active!==null||generating)return;
  if(!window.confirm(publish?'Generate content and publish to all eligible configured channels?':'Generate new draft content for review?'))return;
  setGenerating(publish?'publish':'drafts');setMessage('');
  try{const result=await api<any>('generate?publish='+String(publish),{},'POST');const r=result.report||{};
   setMessage('Generated '+n(r.generated)+' · stored '+n(r.stored)+' · published '+n(r.published?.length)+' · failed '+n(r.failed?.length)+'. Review the resulting content and publishing records.');
   await qc.invalidateQueries({queryKey:['content']});await qc.invalidateQueries({queryKey:['publications']});
  }catch(e){setMessage(errText(e))}finally{setGenerating(null)}
 };
 return <>
  <div className="page-heading"><div><span className="eyebrow">EDITORIAL</span><h1>Content desk.</h1><p>Generate, preview, approve and publish with real server feedback.</p></div>
   <div className="toolbar"><button className="mini-button" disabled={!!generating||active!==null} onClick={()=>q.refetch()}><RefreshCcw size={16}/> Refresh</button>
   <button className="button secondary" disabled={!!generating||active!==null} onClick={()=>generate(false)}>{generating==='drafts'?<Loader2 className="spin" size={16}/>:<Megaphone size={16}/>} Generate drafts</button>
   <button className="button primary" disabled={!!generating||active!==null} onClick={()=>generate(true)}>{generating==='publish'?<Loader2 className="spin" size={16}/>:<Send size={16}/>} Generate & publish</button></div>
  </div>
  <Panel title="Content inventory" subtitle="Approval first for supported distribution channels">
   {generating&&<Loading label="Generating through FastAPI — awaiting server acknowledgment…"/>}
   {message&&<ResultNote kind={/^(Action acknowledged|Generated)/.test(message)?'info':'error'} text={message}/>}
   {q.isPending?<Loading/>:q.isError?<DataError error={q.error} retry={()=>q.refetch()}/>:<div className="scroll-table"><table><thead><tr><th>Template</th><th>Platform</th><th>Date</th><th>Status</th><th>Actions</th></tr></thead><tbody>{(q.data?.content||[]).map((item:any)=><tr key={item.id}><td>{item.template}</td><td>{item.platform}</td><td>{item.publish_date}</td><td><span className="status-label">{item.status}</span></td><td><div className="table-actions">{active===item.id?<Loader2 size={16} className="spin"/>:null}
    <button className="mini-button" disabled={active!==null||!!generating} onClick={()=>setSelected(item)}>View</button>
    {item.status==='DRAFT'?<button className="mini-button" disabled={active!==null||!!generating} onClick={()=>act(item.id,'approve')}>Approve</button>:null}
    {item.status!=='PUBLISHED'&&!['instagram','facebook','tiktok','youtube','x'].includes(item.platform)?<button className="mini-button" disabled={active!==null||!!generating} onClick={()=>act(item.id,'publish')}>Publish</button>:null}</div></td></tr>)}</tbody></table>{!q.data?.content?.length&&<Empty/>}</div>}
  </Panel>
  {selected&&<Panel title="Content review" subtitle="Verify messaging before approving or posting" action={<button className="mini-button" onClick={()=>setSelected(null)}><X size={15}/> Close</button>}>
    <pre className="json-dump">{JSON.stringify(selected.payload||selected,null,2)}</pre>
   </Panel>}
 </>;
}

function Publishing() {
 const q=useQuery({queryKey:['publications'],queryFn:()=>api<any>('publications?limit=150')});
 const [busy,setBusy]=useState(false),[note,setNote]=useState('');
 const retry=async()=>{if(!window.confirm('Retry only failed eligible publications?'))return;setBusy(true);try{const r=await api<any>('retry',{},'POST');setNote('Retried '+n(r.attempted)+'. Recovered '+n(r.recovered)+'.');await q.refetch()}catch(e){setNote(errText(e))}finally{setBusy(false)}};
 return <><div className="page-heading"><div><span className="eyebrow">DISTRIBUTION</span><h1>Publishing history.</h1><p>Failures and confirmations for configured channels.</p></div><button className="button secondary" disabled={busy} onClick={retry}>{busy?<Loader2 className="spin" size={16}/>:<RefreshCcw size={16}/>} Retry failures</button></div><Panel title="Recent delivery events" subtitle="A successful API response is not a substitute for a verified delivery result">{note&&<ResultNote kind="info" text={note}/>}
 {q.isPending?<Loading/>:q.isError?<DataError error={q.error} retry={()=>q.refetch()}/>:<div className="scroll-table"><table><thead><tr><th>Date</th><th>Channel</th><th>Status</th><th>Attempts</th><th>Detail</th></tr></thead><tbody>{(q.data?.publications||[]).map((p:any,i:number)=><tr key={i}><td>{p.publish_date}</td><td>{p.channel}</td><td><span className="status-label">{p.status}</span></td><td>{n(p.attempts)}</td><td>{p.last_error||p.external_id||'—'}</td></tr>)}</tbody></table>{!q.data?.publications?.length&&<Empty/>}</div>}</Panel></>;
}
function Referrals() {
 const q=useQuery({queryKey:['referrals'],queryFn:()=>api<any>('referrals')});const [code,setCode]=useState(''),[name,setName]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 const add=async(e:React.FormEvent)=>{e.preventDefault();setBusy(true);try{await api('referrals',{code,name},'POST');setCode('');setName('');setMessage('Referral link created.');await q.refetch()}catch(error){setMessage(errText(error))}finally{setBusy(false)}};
 return <><div className="page-heading"><div><span className="eyebrow">GROWTH</span><h1>Referrals.</h1><p>Manage partner codes and attribution links.</p></div></div><div className="split"><Panel title="New referral" subtitle="Codes are normalized by the backend"><form className="editor" onSubmit={add}><label>Partner name<input required value={name} onChange={e=>setName(e.target.value)}/></label><label>Referral code<input required value={code} onChange={e=>setCode(e.target.value)}/></label><button className="button primary" disabled={busy} type="submit">{busy?<Loader2 className="spin" size={16}/>:<Users size={16}/>} Create link</button>{message&&<ResultNote kind={message.includes('created')?'success':'error'} text={message}/>}</form></Panel><Panel title="Partner codes" subtitle="Saved in the backend">{q.isPending?<Loading/>:<div className="data-rows">{(q.data?.referrals||[]).map((r:any)=><div key={r.id}><span>{r.name||r.code}</span><b>{r.code}</b></div>)}</div>}</Panel></div></>;
}
function Settings() {
 const qc=useQueryClient();const q=useQuery({queryKey:['settings'],queryFn:()=>api<any>('settings')});
 const [draft,setDraft]=useState<any>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 useEffect(()=>{if(q.data?.settings)setDraft(structuredClone(q.data.settings))},[q.data]);
 const save=async()=>{if(!draft || !window.confirm('Save these operational settings?'))return;setBusy(true);
  try{const keys=['engine_enabled','channel_enabled','channel_auto_publish','schedule'];const patch=Object.fromEntries(keys.filter(k=>k in draft).map(k=>[k,draft[k]]));await api('settings',patch,'POST');setMessage('Settings saved and acknowledged by backend.');await qc.invalidateQueries({queryKey:['settings']});}
  catch(e){setMessage(errText(e))}finally{setBusy(false)}
 };
 const change=(key:string,value:any)=>setDraft((prev:any)=>({...prev,[key]:value}));
 const changeItem=(key:string,item:string,value:any)=>change(key,{...(draft?.[key]||{}),[item]:value});
 return <><div className="page-heading"><div><span className="eyebrow">CONFIGURATION</span><h1>Growth settings.</h1><p>Controlled changes to the engine, channels and publishing schedule.</p></div></div>
 {q.isPending?<Loading/>:q.isError?<DataError error={q.error} retry={()=>q.refetch()}/>:draft?<Panel title="Operational controls" subtitle="Only the existing backend-supported settings are changed">
 <div className="settings-grid"><div><h3>Engine</h3><label className="check"><input type="checkbox" checked={!!draft.engine_enabled} onChange={e=>change('engine_enabled',e.target.checked)}/> Enable growth engine</label></div>
 {(['channel_enabled','channel_auto_publish'] as const).map(key=><div key={key}><h3>{key==='channel_enabled'?'Connected channels':'Auto-publish permissions'}</h3>{Object.entries(draft[key]||{}).map(([k,v])=><label className="check" key={k}><input type="checkbox" checked={!!v} onChange={e=>changeItem(key,k,e.target.checked)}/>{k}</label>)}</div>)}
 <div><h3>Schedules (UTC)</h3>{Object.entries(draft.schedule||{}).map(([k,v])=><label key={k} className="setting-line">{k}<input value={String(v??'')} onChange={e=>changeItem('schedule',k,e.target.value)}/></label>)}</div></div>
 <div className="toolbar"><button className="button primary" disabled={busy} onClick={save}>{busy?<Loader2 className="spin" size={16}/>:<CheckCircle2 size={16}/>} Save settings</button><button className="button secondary" disabled={busy} onClick={()=>setDraft(structuredClone(q.data.settings))}>Discard changes</button></div>{message&&<ResultNote kind={message.includes('saved')?'success':'error'} text={message}/>}
 </Panel>:null}</>;
}

function App() {
 const [session,setSession]=useState<'checking'|'guest'|'ready'>('checking'),[password,setPassword]=useState(''),[loginError,setLoginError]=useState(''),[signing,setSigning]=useState(false),[page,setPage]=useState<Page>('overview'),[mobile,setMobile]=useState(false);
 const [commandOpen,setCommandOpen]=useState(false),[sidebarCompact,setSidebarCompact]=useState(false);
 const qc=useQueryClient();
 const fetching=useIsFetching();
 useEffect(()=>{const onShortcut=(event:KeyboardEvent)=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();setCommandOpen(value=>!value)}};window.addEventListener('keydown',onShortcut);return()=>window.removeEventListener('keydown',onShortcut)},[]);
 const me=useQuery({queryKey:['me'],queryFn:()=>api<any>('admin/me'),retry:false,enabled:session==='checking'});
 useEffect(()=>{if(session==='checking'&&!me.isPending)setSession(me.isError?'guest':'ready')},[session,me.isPending,me.isError]);
 useEffect(()=>{const expired=()=>{qc.clear();setSession('guest');setLoginError('Session expired. Please sign in again.');};window.addEventListener('betsightly:session-expired',expired);return()=>window.removeEventListener('betsightly:session-expired',expired);},[qc]);
 const signIn=async(e:React.FormEvent)=>{e.preventDefault();setSigning(true);setLoginError('');try{await api('admin/login',{password},'POST');setPassword('');await qc.invalidateQueries({queryKey:['me']});const res=await api<any>('admin/me');if(!res.ok)throw Error('Session not confirmed');setSession('ready')}catch(error){setLoginError(errText(error))}finally{setSigning(false)}};
 const signOut=async()=>{try{await api('admin/logout',{},'POST')}catch{}qc.clear();setSession('guest')};
 if(session==='checking')return <div className="auth-screen"><Loading label="Verifying protected admin session…"/></div>;
 if(session==='guest')return <div className="auth-screen"><form className="auth-card" onSubmit={signIn}><div className="brand-mark">B<span>.</span></div><span className="eyebrow">PRIVATE COMMAND CENTER</span><h1>Sign in to BetSightly.</h1><p>Protected football operations, data intelligence and verified publishing.</p><label>Administrator password<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required autoFocus/></label>{loginError&&<ResultNote kind="error" text={loginError}/>}<button className="button primary wide" type="submit" disabled={signing}>{signing?<Loader2 className="spin" size={18}/>:<LockKeyhole size={17}/>} Secure sign in</button><small>Signed sessions are HttpOnly, Secure and SameSite=Strict. Nothing is stored in the browser beyond the protected session cookie.</small></form></div>;
 const sections:{[key in Page]:React.ReactNode}={overview:<Overview onNavigate={setPage}/>,audience:<Insights page="audience"/>,predictions:<Insights page="predictions"/>, 'analytics-health':<Insights page="analytics-health"/>,manual:<ManualStudio/>,jackpot:<PrivateJackpot/>,sporty:<Operations mode="sporty"/>,readiness:<Operations mode="readiness"/>,content:<Content/>,campaign:<CampaignEditor/>,publishing:<Publishing/>,referrals:<Referrals/>,settings:<Settings/>};
 return <div className="shell"><aside className={'sidebar '+(mobile?'shown ':'')+(sidebarCompact?'compact':'')}><div className="sidebar-brand"><div className="brand-mark">B<span>.</span></div><div className="sidebar-brand-name"><strong>BetSightly</strong><small>COMMAND CENTER</small></div><button className="mobile-close" onClick={()=>setMobile(false)} aria-label="Close menu"><X/></button></div><button type="button" className="sidebar-collapse-toggle" aria-label={sidebarCompact?'Expand sidebar':'Collapse sidebar'} onClick={()=>setSidebarCompact(v=>!v)}>{sidebarCompact?<PanelLeftOpen size={18}/>:<PanelLeftClose size={18}/>}<span>{sidebarCompact?'':'Collapse menu'}</span></button><nav aria-label="Admin navigation">{nav.map((item,i)=>{const Icon=item.icon;return <React.Fragment key={item.id}>{(i===0||item.group!==nav[i-1].group)&&<div className="nav-group">{item.group}</div>}<button className={'nav-item '+(page===item.id?'active':'')} aria-current={page===item.id?'page':undefined} onClick={()=>{setPage(item.id);setMobile(false)}} aria-label={item.label} title={sidebarCompact?item.label:undefined}><Icon size={18}/><span>{item.label}</span>{page===item.id&&<ChevronRight size={14}/>}</button></React.Fragment>})}</nav><div className="sidebar-bottom"><div className="session"><ShieldCheck size={18}/><div><strong>Protected session</strong><span>Render-backed authentication</span></div></div><button onClick={signOut} className="sign-out"><LogOut size={17}/> Sign out</button></div></aside><div className="workspace"><header className="topbar"><div className="topbar-left"><button className="menu-toggle" onClick={()=>setMobile(true)} aria-label="Open menu"><Menu/></button><div className="breadcrumb">BET SIGHTLY <ChevronRight size={13}/> <strong>{nav.find(x=>x.id===page)?.label}</strong></div></div><div className="topbar-right"><button type="button" className="premium-search-trigger" onClick={()=>setCommandOpen(true)} aria-label="Search admin pages"><Search size={16}/><span>Search workspace</span><kbd>Ctrl K</kbd></button><span className={'workspace-activity '+(fetching?'syncing':'')} role="status" aria-live="polite"><span className="workspace-activity-dot" aria-hidden="true"/>{fetching?'Refreshing data…':'Protected workspace'}</span><span className="clock">{new Date().toLocaleDateString('en-NG',{day:'numeric',month:'short',year:'numeric',timeZone:'Africa/Lagos'})}</span></div></header><main className="main">{sections[page]}</main><footer className="footer">BetSightly admin · Secure API through same-origin gateway · Data from production FastAPI</footer></div>{mobile&&<button className="scrim" aria-label="Close menu overlay" onClick={()=>setMobile(false)}/>}<AdminCommandPalette open={commandOpen} onClose={()=>setCommandOpen(false)} items={nav.map(({id,label,group})=>({id,label,group}))} onSelect={id=>{setPage(id as Page);setMobile(false)}}/></div>;
}
export default App;
