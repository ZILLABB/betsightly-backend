import {useMemo, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {AlertTriangle, ArrowDownToLine, CheckCheck, ClipboardCopy, Clock3,
  Database, Loader2, RefreshCcw, ShieldCheck, SlidersHorizontal} from 'lucide-react';
import {api, ApiError} from './api';

type State='upcoming'|'awaiting_verified_final'|'final_pending_grade'|'verified_settled';
export type ResearchGame={
  game_id:string;date:string;home_team:string;away_team:string;
  tipoff_utc:string;tipoff_wat:string;status:State;
  home_win_probability:number|null;
  projected_home_points:number|null;projected_away_points:number|null;
  projected_total:number|null;projected_home_margin:number|null;
  advanced_total:number|null;advanced_home_margin:number|null;
  actual_home_score:number|null;actual_away_score:number|null;
  recorded_models:Record<string,boolean>;settled_models:Record<string,boolean>;
  bookmaker_market_verified:false;sportybet_code:null;
};
type Counts=Record<'moneyline'|'original_score'|'advanced_score',number>;
export type ResearchBoard={
  status:string;generated_at:string;research_only:true;private:true;
  model_promotion_approved:false;bookmaker_verified:false;
  booking_codes_available:false;
  summary:{fixtures:number;forecasts:Counts;verified_settlements:Counts;
    pending_fixtures:number};
  games:ResearchGame[];archive_digest?:string;hosted_source?:string;
};
const num=(v:number|null|undefined,suffix='')=>
  typeof v==='number'&&Number.isFinite(v)?v.toFixed(1)+suffix:'—';
const labels:Record<State,string>={
  upcoming:'Before tip-off',awaiting_verified_final:'Awaiting final',
  final_pending_grade:'Final needs grading',verified_settled:'Verified final'
};
function wat(s:string){
  const d=new Date(s);
  return Number.isNaN(d.getTime())?'Time unavailable':
    d.toLocaleString('en-NG',{timeZone:'Africa/Lagos',weekday:'short',
      day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',hour12:true})+' WAT';
}
function csvExport(items:ResearchGame[]){
  const records=[
    ['ID','UTC','Home','Away','Home win probability','Original total','Advanced total','Home margin','Status'],
    ...items.map(g=>[g.game_id,g.tipoff_utc,g.home_team,g.away_team,
      g.home_win_probability??'',g.projected_total??'',
      g.advanced_total??'',g.projected_home_margin??'',g.status])
  ];
  const data=records.map(row=>row.map(v=>'"'+String(v).replace(/"/g,'""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([data],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;
  a.download='betsightly-private-nba-research.csv';a.click();
  URL.revokeObjectURL(url);
}
export default function BasketballResearch(){
  const [state,setState]=useState('all');
  const [term,setTerm]=useState('');
  const [notice,setNotice]=useState('');
  const [uploadBusy,setUploadBusy]=useState(false);
  const [uploadIssue,setUploadIssue]=useState('');
  const [uploadConfirmed,setUploadConfirmed]=useState(false);
  const q=useQuery<ResearchBoard>({
    queryKey:['nba-private-recorded-research'],
    queryFn:()=>api<ResearchBoard>('admin/nba-research'),
    refetchOnWindowFocus:false,retry:false,staleTime:60000
  });
  const board=q.data;
  const verified=!!board&&board.research_only===true&&board.private===true&&
    board.bookmaker_verified===false&&board.booking_codes_available===false&&
    board.model_promotion_approved===false&&Array.isArray(board.games)&&!!board.summary;
  const items=useMemo(()=>{
    if(!verified)return [];
    return board!.games.filter(g=>{
      const name=(g.home_team+' '+g.away_team+' '+g.game_id).toLowerCase();
      const matches=name.includes(term.trim().toLowerCase());
      const stage=state==='all'||g.status===state||(state==='pending'&&
        (g.status==='awaiting_verified_final'||g.status==='final_pending_grade'));
      return matches&&stage;
    }).slice().sort((a,b)=>a.tipoff_utc.localeCompare(b.tipoff_utc));
  },[board,verified,state,term]);
  async function copy(){
    if(!items.length)return;
    try{
      await navigator.clipboard.writeText(items.map(g=>
        wat(g.tipoff_utc)+' | '+g.home_team+' vs '+g.away_team+
        ' | Home '+(g.home_win_probability==null?'n/a':
          num(g.home_win_probability*100,'%'))+
        ' | Total '+num(g.projected_total)+
        ' | Advanced '+num(g.advanced_total)).join('\n'));
      setNotice(items.length+' archived NBA games copied.');
    }catch{setNotice('Clipboard unavailable. Use Export CSV.');}
  }
  async function uploadArchive(event:import('react').ChangeEvent<HTMLInputElement>){
    const file=event.target.files?.[0];
    event.target.value='';
    if(!file||uploadBusy)return;
    setUploadBusy(true);
    setUploadIssue('');
    setUploadConfirmed(false);
    try{
      if(file.size>750_000)throw Error('Private NBA file exceeds 750 KB. No data was uploaded.');
      const raw=await file.text();
      const data:unknown=JSON.parse(raw);
      if(!data||typeof data!=='object'||Array.isArray(data)||
        (data as any).version!=='betsightly-nba-private-archive-v1'||
        (data as any).research_only!==true)
        throw Error('Choose a verified BetSightly NBA archive export, not arbitrary JSON.');
      const saved=await api<{status:string;digest:string;fixture_count:number}>(
        'admin/nba-research/import',data);
      if(saved.status!=='saved_and_verified'&&saved.status!=='already_saved')
        throw Error('Backend did not confirm saved NBA research. Do not retry blindly.');
      const checked=await q.refetch();
      if(checked.isError||checked.data?.archive_digest!==saved.digest)
        throw Error('Upload response received, but database readback did not confirm the same archive. Check status before resubmitting.');
      setUploadConfirmed(true);
      setNotice(saved.fixture_count+' NBA fixtures verified in private database. Existing football remains unchanged.');
    }catch(error){
      setUploadIssue(error instanceof Error?error.message:'NBA archive upload failed.');
    }finally{setUploadBusy(false);}
  }
  const status=q.error instanceof ApiError?q.error.status:0;
  return <section className="nba-workspace">
    <header className="page-heading nba-heading">
      <div><span className="eyebrow">PRIVATE BASKETBALL / RESEARCH ONLY</span>
        <h1>NBA intelligence desk.</h1>
        <p>Original before-tipoff evidence, independent scoring models,
          and verified finals. Football records remain separate.</p></div>
      <button type="button" className="button secondary" disabled={q.isFetching}
        onClick={()=>void q.refetch()}>
        <RefreshCcw size={15} className={q.isFetching?'spin':''}/> Refresh records
      </button>
    </header>
    <div className="nba-import">
      <div><strong>Secure forecast archive</strong>
        <span>Import the original signed NBA research bundle exported on your laptop.
          Admin-only, append-only and never shared with football results.</span></div>
      <label className={'button secondary '+(uploadBusy?'nba-upload-busy':'')}>
        <Database size={15}/>{uploadBusy?'Verifying archive…':'Import research archive'}
        <input aria-label="Choose exported NBA JSON archive" type="file"
          accept=".json,application/json" disabled={uploadBusy}
          onChange={e=>void uploadArchive(e)}/>
      </label>
    </div>
    {uploadIssue&&<div className="nba-upload-error" role="alert">
      <AlertTriangle size={17}/>{uploadIssue}
    </div>}
    {uploadConfirmed&&<div className="nba-notice" role="status">
      <CheckCheck size={15}/> NBA archive saved and confirmed by database readback.
    </div>}
    <div className="nba-disclaimer" role="note"><ShieldCheck size={19}/>
      <span><strong>Evaluation only.</strong> No SportyBet basketball booking code,
        verified market lines, stakes, public picks or guaranteed outcomes.</span></div>
    {q.isPending?<div className="nba-state" role="status" aria-live="polite">
      <Loader2 size={24} className="spin"/>
      <span><strong>Reading signed NBA records…</strong>
        Checking original forecasts and verified settlements.</span>
    </div>:q.isError?<div className="nba-state" role="alert">
      <AlertTriangle size={22}/>
      <div><strong>NBA research is not available.</strong>
        <p>{status===404?'Private NBA API is not enabled on the backend.':
        status===503?'NBA archives are not yet available on the hosted server.':
        'The verified NBA data request failed.'}</p>
        <small>Your 16 locally archived games are not automatically stored on Vercel or Render.
          This is not a football outage.</small>
        <button className="button secondary" onClick={()=>void q.refetch()}>
          <RefreshCcw size={15}/> Retry read-only request</button></div>
    </div>:!verified?<div className="nba-state" role="alert">
      <AlertTriangle size={22}/>
      <div><strong>Unverified data withheld.</strong>
        <p>Backend response did not satisfy the private research contract.
          No predictions have been invented.</p></div>
    </div>:<>
      <div className="nba-metrics" aria-label="NBA forecast evidence">
        <div><small>Recorded fixtures</small><strong>{board.summary.fixtures}</strong>
          <span>Distinct game IDs</span></div>
        <div><small>Moneyline forecasts</small><strong>{board.summary.forecasts?.moneyline??0}</strong>
          <span>Saved before tip-off</span></div>
        <div><small>Original score model</small><strong>{board.summary.forecasts?.original_score??0}</strong>
          <span>Reference model</span></div>
        <div><small>Advanced score model</small><strong>{board.summary.forecasts?.advanced_score??0}</strong>
          <span>Independent experiment</span></div>
      </div>
      <div className="nba-toolbar">
        <label><SlidersHorizontal size={16}/><span className="sr-only">Fixture status</span>
          <select value={state} onChange={e=>setState(e.target.value)}>
            <option value="all">All fixtures</option>
            <option value="upcoming">Upcoming</option>
            <option value="pending">Pending settlement</option>
            <option value="verified_settled">Verified finals</option>
          </select></label>
        <label><Database size={16}/><span className="sr-only">Find NBA fixture</span>
          <input value={term} onChange={e=>setTerm(e.target.value)}
            placeholder="Search team or fixture ID"/></label>
        <button type="button" className="button secondary" disabled={!items.length}
          onClick={()=>void copy()}><ClipboardCopy size={15}/> Copy games</button>
        <button type="button" className="button secondary" disabled={!items.length}
          onClick={()=>csvExport(items)}><ArrowDownToLine size={15}/> Export CSV</button>
      </div>
      {notice&&<p role="status" className="nba-notice">{notice}</p>}
      <div className="nba-table-wrap">
        <table className="nba-table">
          <caption>{items.length} of {board.summary.fixtures} saved NBA games · times WAT</caption>
          <thead><tr><th>Fixture &amp; kickoff</th><th>Home win</th>
            <th>Team points</th><th>Projected total</th>
            <th>Home margin</th><th>Verified result</th></tr></thead>
          <tbody>{items.map(g=><tr key={g.game_id}>
            <td><div className="nba-fixture"><strong>{g.home_team}<span> vs </span>
              {g.away_team}</strong><small><Clock3 size={12}/>{wat(g.tipoff_utc)}</small>
              <small>Game ID {g.game_id}</small></div></td>
            <td><strong className="nba-value">{g.home_win_probability==null?'—':
              num(g.home_win_probability*100,'%')}</strong><small>Research only</small></td>
            <td><strong className="nba-value">{num(g.projected_home_points)}
              {' / '}{num(g.projected_away_points)}</strong><small>Home / Away</small></td>
            <td><strong className="nba-value">{num(g.projected_total)}</strong>
              <small>Advanced {num(g.advanced_total)}</small></td>
            <td><strong className="nba-value">{g.projected_home_margin!=null&&g.projected_home_margin>0?'+':''}{num(g.projected_home_margin)}</strong>
              <small>Points, not bookmaker line</small></td>
            <td><span className={'nba-status nba-status-'+g.status}>{labels[g.status]||'Unverified'}</span>
              {g.status==='verified_settled'&&g.actual_home_score!=null&&g.actual_away_score!=null&&
                <small>Final {g.actual_home_score}–{g.actual_away_score}</small>}</td>
          </tr>)}
          {!items.length&&<tr><td colSpan={6} className="nba-empty">
            No saved fixtures match the selected filters.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="nba-foot"><CheckCheck size={17}/>
        <span>Verified grades: moneyline {board.summary.verified_settlements?.moneyline??0};
          original score {board.summary.verified_settlements?.original_score??0};
          advanced score {board.summary.verified_settlements?.advanced_score??0}.
          No bookmaker odds or NBA code generation.</span>
      </div>
    </>}
  </section>;
}