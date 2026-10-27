import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const source=readFileSync(new URL('../src/nbaMarketPaperGrade.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{
  module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022,
}}).outputText;
const {frozenMarketGrade,frozenAlternativeGrade,paperGradeLabel}=
  await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));

const before={game_id:'401909868',observed_at:'2026-10-26T12:40:00Z',
  reference_total:229.5,paper_direction:'over',paper_grade:'pending'};
const verified={...before,paper_grade:'incorrect'};

test('reconciles old pending snapshot to later verified frozen first-observation grade',()=>{
  assert.equal(frozenMarketGrade(before,verified),'incorrect');
  assert.equal(paperGradeLabel(frozenMarketGrade(before,verified)),'Incorrect');
});

test('never imports final grade from another line, repricing, market side or game',()=>{
  for(const changed of [
    {...before,game_id:'401909869'},
    {...before,observed_at:'2026-10-26T13:50:00Z'},
    {...before,reference_total:231.5},
    {...before,paper_direction:'under'},
  ]){
    assert.equal(frozenMarketGrade(changed,verified),'not_evaluated');
  }
  assert.equal(frozenMarketGrade(before,null),'not_evaluated');
});

test('only first frozen reference line is graded, never neighbouring totals',()=>{
  assert.equal(frozenAlternativeGrade(before,verified,{
    game_id:before.game_id,observed_at:before.observed_at,line:229.5,
  }),'incorrect');
  assert.equal(frozenAlternativeGrade(before,verified,{
    game_id:before.game_id,observed_at:before.observed_at,line:230.5,
  }),'not_evaluated');
  assert.equal(frozenAlternativeGrade({...before,reference_total:230.5},verified,{
    game_id:before.game_id,observed_at:before.observed_at,line:229.5,
  }),'not_evaluated');
});

test('does not invent settled grade from unverified source value',()=>{
  assert.equal(frozenMarketGrade(before,before),'pending');
  assert.equal(frozenMarketGrade(before,{...before,paper_grade:'won'}),'not_evaluated');
  assert.equal(paperGradeLabel('not_evaluated'),'Not evaluated');
});
