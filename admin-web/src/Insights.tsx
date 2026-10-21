import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {AlertTriangle, Loader2, RefreshCcw} from 'lucide-react';
import {api} from './api';

export type InsightPage='audience'|'predictions'|'analytics-health';
const number=(v:any)=>v==null?'—':typeof v==='number'?v.toLocaleString():String(v);
const rate=(v:any)=>v==null?'—':(100*Number(v)).toFixed(1)+'%';
function Table({cols,rows}:{cols:string[];rows:Array<Array<any>>}){
 if(!rows.length)return <div className="empty">No evidence for this period; nothing has been estimated.</div>;
 return <div className="scroll-table"><table><thead><tr>{cols.map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{r.map((v,j)=><td key={j}>{v===null||v===undefined?'—':String(v)}</td>)}</tr>)}</tbody></table></div>;
}
function Panel({title,detail,children}:{title:string;detail?:string;children:React.ReactNode}){
 return <section className="panel"><header className="panel-head"><div><h2>{title}</h2>{detail&&<p>{detail}</p>}</div></header>{children}</section>;
}
function Metric({label,value}:{label:string;value:any}){return <div className="metric"><span>{label}</span><strong>{number(value)}</strong></div>}
function SegmentTable({title,rows}:{title:string;rows:any[]}) {
 return <Panel title={title} detail="Anonymous audience; visitor IDs are not revealed"><Table cols={['Segment','Visitors','Returning','Sessions','Prediction viewers','Builders','Code copiers','Copy rate']} rows={(rows||[]).map(r=>[r.key,number(r.visitors),number(r.returning),number(r.sessions),number(r.prediction_viewers),number(r.builders),number(r.code_copiers),rate(r.copy_conversion)])}/></Panel>
}
function Audience({s}:{s:any}){
 const active=s.active_users||{},totals=s.totals||{},r=s.retention||{},pr=s.prediction_day_return||{};
 return <>
 <div className="metric-grid"><Metric label="Daily active" value={active.dau}/><Metric label="Weekly active" value={active.wau}/><Metric label="Monthly active" value={active.mau}/><Metric label="New visitors" value={totals.new_visitors}/><Metric label="Returning" value={totals.returning_visitors}/><Metric label="Prediction-day return" value={rate(pr.rate)}/></div>
 <Panel title="Retention cohorts" detail="Rates include explicit eligible sample sizes"><div className="metric-grid">{Object.entries(r).map(([k,v])=><div className="metric" key={k}><span>{k} retention</span><strong>{rate((v as any)?.rate)}</strong><small>{number((v as any)?.returned)} of {number((v as any)?.eligible)} eligible</small></div>)}</div>{!Object.keys(r).length&&<div className="empty">No retention cohorts available.</div>}</Panel>
 <SegmentTable title="Geographic audience" rows={s.by_country||[]}/>
 <SegmentTable title="Traffic source quality" rows={s.by_source||[]}/>
 <Panel title="Devices and conversion" detail="Keep unknown device and missing rates visible"><Table cols={['Device','Visitors','Prediction rate','Builder rate','Copy rate','SportyBet opens','Return rate']} rows={(s.by_device||[]).map((v:any)=>[v.key,number(v.visitors),rate(v.prediction_view_rate),rate(v.builder_usage_rate),rate(v.copy_conversion),rate(v.sportybet_open_rate),rate(v.return_rate)])}/></Panel>
 <div className="split"><SegmentTable title="Operating systems" rows={s.by_os||[]}/><SegmentTable title="Browsers" rows={s.by_browser||[]}/></div>
 </>;
}
function Predictions({s}:{s:any}){
 const bb=s.builder_backend||{},b=s.builder||{},perf=s.prediction_performance||{};
 return <>
 <div className="metric-grid"><Metric label="Builder users" value={s.totals?.builder_users}/><Metric label="Backend builder requests" value={bb.requests}/><Metric label="Tickets produced" value={bb.tickets_produced}/><Metric label="Ticket rate" value={rate(bb.ticket_rate)}/><Metric label="Average legs" value={b.average_legs}/><Metric label="Average bookmaker odds" value={b.average_actual_odds}/></div>
 <Panel title="Settled prediction record" detail="Official engine results only; editorial manual selections stay distinct"><Table cols={['Tier','Settled','Won','Lost','Win rate','ROI','Level-stake profit']} rows={Object.entries(perf).map(([name,v])=>{const d=v as any;return [name,number(d.settled),number(d.won),number(d.lost),rate(d.win_rate),rate(d.roi),number(d.profit)]})}/></Panel>
 <Panel title="Builder target odds" detail="Demand by user target, not implied booking success"><Table cols={['Target','Requests','Tickets','Rate']} rows={(bb.by_target||[]).map((v:any)=>[v.target,number(v.requests),number(v.tickets_produced),rate(v.ticket_rate)])}/></Panel>
 <SegmentTable title="Product usage" rows={s.by_product_source||[]}/>
 </>;
}
function AnalyticsHealth({s}:{s:any}){
 const h=s.analytics_health||{},p=h.provider||{},q=h.quality||s.analytics_quality||{},c=s.metric_contracts||{},source=s.sources||{};
 const quality=[['Geography',q.geo_coverage],['Device detection',q.device_coverage],['OS detection',q.os_coverage],['Browser detection',q.browser_coverage],['Referrer',q.referrer_attribution],['Stable visitor ID',q.stable_visitor_coverage]];
 return <>
 <div className="metric-grid"><Metric label="Human analytics state" value={p.status||'Unknown'}/><Metric label="Backend facts state" value={source.backend_facts?.status||'Unknown'}/><Metric label="Dual-write cutoff" value={h.dual_write_until||'Not set'}/></div>
 <Panel title="Provider diagnostics" detail="Unknown and stale data are not counted as healthy"><div className="data-rows">{[['Source',p.source],['Status',p.status],['Age in seconds',p.freshness_seconds],['Reason',p.reason],['Backend evidence age',source.backend_facts?.freshness_seconds]].map(([k,v])=><div key={String(k)}><span>{k}</span><b>{number(v)}</b></div>)}</div></Panel>
 <Panel title="Data completeness" detail="Rates are reported without fabricating missing values"><div className="metric-grid">{quality.map(([k,v])=><Metric key={String(k)} label={String(k)} value={rate(v)}/>)}</div></Panel>
 <Panel title="Metric denominators and sample integrity" detail="Every conversion rate includes its numerator and denominator"><Table cols={['Metric','Numerator','Denominator','Rate','Sample']} rows={Object.entries(c).map(([name,v])=>{const x=v as any;return [name,number(x.numerator),number(x.denominator),rate(x.rate),x.sample_status||'Unknown']})}/></Panel>
 </>;
}
export default function Insights({page}:{page:InsightPage}){
 const [days,setDays]=useState(7);
 const q=useQuery({queryKey:['analytics',days],queryFn:()=>api<any>('analytics?days='+days)});
 const title=page==='audience'?'Users & retention':page==='predictions'?'Predictions & builder':'Analytics health';
 const description=page==='audience'?'Actual visitors and returning behavior':page==='predictions'?'Builder engagement and separated, settled engine performance':'Freshness, denominators and missing provider evidence';
 return <>
 <div className="page-heading"><div><span className="eyebrow">OPERATIONAL ANALYTICS</span><h1>{title}.</h1><p>{description}</p></div><div className="toolbar">{[1,7,30,90].map(d=><button key={d} className={days===d?'chip active':'chip'} onClick={()=>setDays(d)}>{d===1?'Today':d+' days'}</button>)}<button className="mini-button" onClick={()=>q.refetch()}><RefreshCcw size={15}/> Refresh</button></div></div>
 {q.isPending?<div className="loading"><Loader2 className="spin" size={18}/> Fetching verified analytics…</div>:q.isError?<div className="notice warning"><AlertTriangle size={16}/> {q.error instanceof Error?q.error.message:'Analytics request failed'} <button className="mini-button" onClick={()=>q.refetch()}>Retry</button></div>:!q.data?.summary?<div className="empty">The backend did not return an analytics summary.</div>:page==='audience'?<Audience s={q.data.summary}/>:page==='predictions'?<Predictions s={q.data.summary}/>:<AnalyticsHealth s={q.data.summary}/>}
 </>;
}
