import {useMemo, useState} from 'react';
import {AlertTriangle, Clipboard, Loader2, Search, ShieldCheck, Tags} from 'lucide-react';
import {api} from './api';

type MarketOption = {key:string;label:string;group:string;activation:string;
  approved_fixture_count:number;auto_selection_eligible:boolean;
  default_excluded:boolean;availability_status:string};
type Catalog = {status:string;reason?:string;source?:string;market_count?:number;
  full_sportybet_catalog?:boolean;approved_market_count?:number;
  markets?:MarketOption[];note?:string};
type Props = {preferences:()=>Record<string,unknown>};

const marketGroup=(x:string)=>{
 const labels:Record<string,string>={
  match_result:'1X2 results',double_chance:'Double chance',dnb:'Draw no bet',
  goals:'Total goals',team_goals_home:'Home team goals',team_goals_away:'Away team goals',
  btts:'Both teams to score',
 };
 return labels[x]||x;
};

const statusText=(x:MarketOption)=>
 x.auto_selection_eligible
  ?'Approved on '+x.approved_fixture_count+' fixtures'
  :x.default_excluded
   ?'Mapped · Under market excluded by default'
   :x.activation!=='ACTIVE'
    ?'Mapped · Not activated for BetSightly booking'
    :'Mapped · No approved selection for current filters';

export default function MarketExplorer({preferences}:Props){
 const [catalog,setCatalog]=useState<Catalog|null>(null);
 const [query,setQuery]=useState('');
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState('');
 const [copied,setCopied]=useState('');
 const filtered=useMemo(()=>{
  const term=query.trim().toLowerCase();
  return (catalog?.markets||[]).filter(x=>
   !term||[x.key,x.label,marketGroup(x.group),statusText(x)].some(s=>s.toLowerCase().includes(term))
  );
 },[catalog,query]);
 const grouped=useMemo(()=>{
  const result=new Map<string,MarketOption[]>();
  for(const item of filtered){
   const name=marketGroup(item.group);
   if(!result.has(name))result.set(name,[]);
   result.get(name)?.push(item);
  }
  return [...result.entries()];
 },[filtered]);
 const load=async()=>{
  if(loading)return;
  setLoading(true);setError('');
  try{
   const res=await api<Catalog>('private-jackpot/market-catalog',preferences(),'POST');
   if(res.status!=='success')throw new Error(res.reason||'Market status unavailable');
   setCatalog(res);
  }catch(e){setError(e instanceof Error?e.message:'Market status unavailable')}
  finally{setLoading(false)}
 };
 const copy=async(key:string)=>{
  try{
   await navigator.clipboard.writeText('Home vs Away | '+key);
   setCopied(key);
  }catch(e){setError('Clipboard denied. You can type the canonical key '+key+' after | instead.')}
 };
 return <section className="panel jackpot-markets">
  <header className="panel-head"><div>
   <h2>SportyBet mapped market options</h2>
   <p>Explore every audited BetSightly market mapping, including restricted ones. This is not the entire SportyBet bookmaker catalogue.</p>
  </div><Tags size={21}/></header>
  <button className="button secondary" type="button" onClick={load} disabled={loading}>
   {loading?<Loader2 size={17} className="spin"/>:<Search size={17}/>}
   {loading?'Checking current approved prices…':catalog?'Refresh today’s market availability':'Browse all mapped market options'}
  </button>
  {error&&<div className="notice warning" role="alert"><AlertTriangle size={17}/><div>{error}</div></div>}
  {catalog&&<>
   <div className="notice info"><ShieldCheck size={17}/><div>
    <strong>{catalog.market_count||0} verified market mappings</strong>, of which {catalog.approved_market_count||0} currently have approved fixtures for these filters.
    SportyBet may offer further markets not integrated into BetSightly. An outcome must be mapped, approved and live priced to be bookable.
   </div></div>
   <label className="jackpot-market-search">Search markets
    <input type="search" value={query} onChange={e=>setQuery(e.target.value)}
     placeholder="BTTS, goals, team goals, double chance…"/>
   </label>
   <div className="jackpot-market-groups">
    {grouped.map(([label,options])=><section key={label}>
     <h3>{label} · {options.length}</h3>
     {options.map(option=><div key={option.key} className="jackpot-market-option">
      <div><strong>{option.label}</strong>
       <small>{option.key} · {statusText(option)}</small>
      </div>
      {option.auto_selection_eligible
       ?<button type="button" className="mini-button" title="Copy a paste-line template using this exact market"
        onClick={()=>copy(option.key)}><Clipboard size={14}/>
        {copied===option.key?'Copied':'Copy format'}</button>
       :<span className="jackpot-market-inactive">Not eligible</span>}
     </div>)}
    </section>)}
   </div>
   {filtered.length===0&&<p>No market name matches this search.</p>}
   <p className="muted">Paste format: <code>Home vs Away | over_2_5 @1.75</code>. The @price is a reference only. Current bookmaker pricing and exact market outcomes are verified before a code is returned.</p>
  </>}
 </section>;
}
