/** The first recorded bookmaker observation is the only evaluated reference.
 * Snapshot responses are immutable and can legitimately retain stale "pending"
 * fields after verified settlement in the separate frozen-history ledger.
 * Never transfer a grade across different prices, thresholds or directions.
 */
export type NbaFrozenReferenceKey={
  game_id:string;observed_at:string;reference_total:number;
  paper_direction:'over'|'under'|null;paper_grade:string;
};
export type NbaQuotedLineKey={
  game_id:string;observed_at:string;line:number;
};
export type PaperGrade='correct'|'incorrect'|'push'|'pending'|'not_evaluated';

export function frozenMarketGrade(
  market:NbaFrozenReferenceKey, first:NbaFrozenReferenceKey|null|undefined,
):PaperGrade{
  if(!first||market.game_id!==first.game_id||
     market.observed_at!==first.observed_at||
     market.reference_total!==first.reference_total||
     market.paper_direction!==first.paper_direction) return 'not_evaluated';
  const grade=first.paper_grade;
  return grade==='correct'||grade==='incorrect'||grade==='push'||grade==='pending'
    ?grade:'not_evaluated';
}

export function frozenAlternativeGrade(
  latest:NbaFrozenReferenceKey, first:NbaFrozenReferenceKey|null|undefined,
  alternative:NbaQuotedLineKey,
):PaperGrade{
  if(!first||alternative.game_id!==latest.game_id||
    alternative.observed_at!==first.observed_at||
    alternative.line!==first.reference_total)return 'not_evaluated';
  return frozenMarketGrade(latest,first);
}

export function paperGradeLabel(grade:PaperGrade):string{
  return grade==='correct'?'Correct':grade==='incorrect'?'Incorrect':
    grade==='push'?'Push':grade==='pending'?'Pending':'Not evaluated';
}
