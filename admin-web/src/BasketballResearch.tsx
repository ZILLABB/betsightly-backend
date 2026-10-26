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
  const [settling,setSettling]=useState(false);
  const [settlementError,setSettlementError]=useState('');
  const [marketBusy,setMarketBusy]=useState(false);
  const [marketNotice,setMarketNotice]=useState('');
  const [forecastBusy,setForecastBusy]=useState(false);
  const [forecastNotice,setForecastNotice]=useState('');


  const q=useQuery<ResearchBoard>({
    queryKey:['nba-private-recorded-research'],
    queryFn:()=>api<ResearchBoard>('admin/nba-research'),
    refetchOnWindowFocus:false,retry:false,staleTime:60000
  });
  type NbaMarketLine={
    game_id:string;home:string;away:string;line:number;
    over_odds:number;under_odds:number;projected_total:number|null;
    difference:number|null;model_probability:null;expected_value:null;
    recommendation:string;tipoff_utc:string;observed_at:string;
    paper_direction:'over'|'under'|null;paper_grade:string;actual_total:number|null;
  };
  type NbaMarketReport={
    status:string;observed_at?:string;quoted_totals:NbaMarketLine[];
    fixture_matches:number;digest?:string;calibrated_betting_edge:boolean;
  };
  const markets=useQuery<NbaMarketReport>({
    queryKey:['nba-private-market-research'],
    queryFn:()=>api<NbaMarketReport>('admin/nba-research/markets'),
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
  async function checkFinals(){
    if(settling||uploadBusy||!verified)return;
    setSettling(true);setSettlementError('');
    try{
      const result=await api<{status:string;archive_digest:string;new_finals:number;
        new_settlements:Record<string,number>;failed_dates?:Array<{date:string;error:string}>}>(
        'admin/nba-research/settle',{},'POST');
      const checked=await q.refetch();
      if(checked.isError||!checked.data||
        checked.data.archive_digest!==result.archive_digest)
        throw Error('Score check returned, but the private database did not confirm its result. Refresh before repeating.');
      const count=Object.values(result.new_settlements||{}).reduce((total,n)=>total+n,0);
      setNotice(result.status==='settled_and_verified'
        ?result.new_finals+' new NBA final(s), '+count+' model grades verified and saved.'
        :result.status==='idle'
          ?'No eligible NBA finals are awaiting verification yet.'
          :'No new verified NBA finals. Unverified games remain pending; no result was guessed.');
      if(result.failed_dates?.length)
        setSettlementError(result.failed_dates.length+' NBA source day(s) could not be verified. These games remain pending.');
    }catch(error){
      setSettlementError(error instanceof Error?error.message:'NBA score verification unavailable.');
    }finally{setSettling(false);}
  }
  async function refreshMarketResearch(){
    if(marketBusy||settling||uploadBusy||!verified)return;
    setMarketBusy(true);setMarketNotice('');
    try{
      const captured=await api<NbaMarketReport>(
        'admin/nba-research/markets/refresh',{},'POST');
      if(captured.status!=='saved'&&captured.status!=='already_saved')
        throw Error('No complete market crawl was confirmed by staging.');
      const checked=await markets.refetch();
      if(checked.isError||checked.data?.digest!==captured.digest)
        throw Error('Market source responded, but private database readback did not confirm the same observation.');
      setMarketNotice(captured.fixture_matches+' exact NBA events archived. No bets or recommendations generated.');
    }catch(error){
      setMarketNotice(error instanceof Error?error.message:'Bookmaker market research unavailable.');
    }finally{setMarketBusy(false);}
  }
  async function runResearchForecasts(){
    if(!verified||forecastBusy||settling||marketBusy||uploadBusy)return;
    setForecastBusy(true);setForecastNotice('');
    try{
      const result=await api<{status:string;archive_digest:string;
        new_forecasts:Record<string,number>;fixture_count?:number}>(
        'admin/nba-research/forecast',{},'POST');
      const checked=await q.refetch();
      if(checked.isError||checked.data?.archive_digest!==result.archive_digest)
        throw Error('Research forecast response was not confirmed by the NBA database.');
      const count=Object.values(result.new_forecasts||{}).reduce((sum,n)=>sum+n,0);
      setForecastNotice(result.status==='archived_before_tipoff'
        ?count+' new signed research forecasts archived before tipoff. No betting tips or codes published.'
        :result.status==='no_upcoming_eligible_source_window'
          ?'No new eligible fixture is available in the verified 48-hour source window.'
          :result.status==='archive_capacity_reached'
            ?'Archive capacity reached. Existing forecasts remain safe; extend storage before new capture.'
            :'No new research predictions. Existing forecasts remain unchanged.');
    }catch(error){
      setForecastNotice(error instanceof Error?error.message:'NBA daily forecast inputs unavailable.');
    }finally{setForecastBusy(false);}
  }
  const status=q.error instanceof ApiError?q.error.status:0;
  return <section className="nba-workspace">
    <header className="page-heading nba-heading">
      <div><span className="eyebrow">PRIVATE BASKETBALL / RESEARCH ONLY</span>
        <h1>NBA intelligence desk.</h1>
        <p>Original before-tipoff evidence, independent scoring models,
          and verified finals. Football records remain separate.</p></div>
      <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
        <button type="button" className="button secondary" disabled={q.isFetching||settling}
          onClick={()=>void q.refetch()}>
          <RefreshCcw size={15} className={q.isFetching?'spin':''}/> Refresh records
        </button>
        <button type="button" className="button secondary"
          disabled={!verified||settling||uploadBusy} onClick={()=>void checkFinals()}>
          {settling?<Loader2 size={15} className="spin"/>:<CheckCheck size={15}/>}
          {settling?'Verifying final scores…':'Check NBA finals'}
        </button>
      </div>
    </header>
    <section className="nba-import" aria-label="Prospective NBA forecast capture">
      <div>
        <strong>Cloud research forecast capture</strong>
        <span>Generate only eligible before-tipoff moneyline and original score forecasts
          using verified prior-season data. Advanced forecasts require separate boxscore evidence.</span>
      </div>
      <button type="button" className="button secondary"
        disabled={!verified||forecastBusy||settling||marketBusy||uploadBusy}
        onClick={()=>void runResearchForecasts()}>
        {forecastBusy?<Loader2 size={15} className="spin"/>:<Clock3 size={15}/>}
        {forecastBusy?'Validating historical data…':'Generate new NBA research'}
      </button>
    </section>
    {forecastNotice&&<p role="status" className="nba-notice">{forecastNotice}</p>}
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
    {settlementError&&<div className="nba-upload-error" role="alert">
      <AlertTriangle size={17}/>{settlementError}
    </div>}
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
      <section className="nba-import" aria-label="Private NBA bookmaker market research"
        style={{marginTop:18,display:'grid',gap:14}}>
        <div>
          <strong>Live bookmaker lines · private research</strong>
          <span>Capture exact SportyBet NBA total-point prices and match them to existing
            saved forecasts. This does not generate betting tips, codes, or stakes.</span>
          <small>Snapshots require exact teams, validated kickoff and complete upstream results.</small>
        </div>
        <button type="button" className="button secondary"
          disabled={!verified||marketBusy||settling||uploadBusy}
          onClick={()=>void refreshMarketResearch()}>
          {marketBusy?<Loader2 size={15} className="spin"/>:<RefreshCcw size={15}/>}
          {marketBusy?'Checking exact bookmaker markets…':'Capture NBA market lines'}
        </button>
      </section>
      {marketNotice&&<p role="status" className="nba-notice">{marketNotice}</p>}
      {markets.data?.observed_at&&
        <p className="nba-disclaimer">Last bookmaker observation: {wat(markets.data.observed_at)}.
          These quoted prices are historical snapshots, not live guaranteed prices.</p>}
      {markets.isError?<p className="nba-disclaimer" role="note">
        Market comparison is disabled or the source is unavailable. Predictions remain research-only.
      </p>:markets.isPending?<p className="nba-disclaimer">
        Reading private bookmaker market observations…
      </p>:<section className="nba-table-wrap" aria-label="Exact NBA total-point prices">
        <table className="nba-table">
          <caption>{markets.data?.quoted_totals?.length??0} exact total-point lines
            · no calibrated betting advantage has been demonstrated</caption>
          <thead><tr><th>Match</th><th>Bookmaker total</th><th>Over</th>
            <th>Under</th><th>Projection</th><th>Difference</th><th>Paper grade</th></tr></thead>
          <tbody>{(markets.data?.quoted_totals??[]).map((m,i)=><tr key={m.game_id+'-'+m.line+'-'+i}>
            <td>{m.home} vs {m.away}<small>{wat(m.tipoff_utc)}</small></td>
            <td>{m.line.toFixed(1)}</td>
            <td>{m.over_odds.toFixed(2)}x</td><td>{m.under_odds.toFixed(2)}x</td>
            <td>{num(m.projected_total)}</td>
            <td>{m.difference==null?'—':num(m.difference)}</td>
            <td>{m.paper_grade==='correct'?'Correct · research only':
                 m.paper_grade==='incorrect'?'Incorrect · research only':
                 m.paper_grade==='push'?'Push':m.paper_direction
                   ?'Awaiting verified final':'No directional forecast'}</td>
          </tr>)}
          {!markets.data?.quoted_totals?.length&&<tr><td colSpan={7}>
            No verified market lines captured. There is no selection recommendation.
          </td></tr>}
          </tbody>
        </table>
      </section>}
      <p className="nba-disclaimer">Prices are observational and may change.
        An Over/Under projection difference is not a winning bet or verified edge.
        NBA market calibration, betting ROI and public publishing remain disabled.</p>
      <div className="nba-foot"><CheckCheck size={17}/>
        <span>Verified grades: moneyline {board.summary.verified_settlements?.moneyline??0};
          original score {board.summary.verified_settlements?.original_score??0};
          advanced score {board.summary.verified_settlements?.advanced_score??0}.
          No bookmaker odds or NBA code generation.</span>
      </div>
    </>}
  </section>;
}