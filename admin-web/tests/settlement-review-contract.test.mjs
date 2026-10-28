import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const app=readFileSync(new URL('../src/App.tsx', import.meta.url),'utf8');
const desk=readFileSync(new URL('../src/SettlementReview.tsx', import.meta.url),'utf8');
const proxy=readFileSync(new URL('../api/proxy.js', import.meta.url),'utf8');

test('protected manual evidence desk appears on production navigation only',()=>{
 assert.match(app, /id:'settlement-review',label:'Settlement review'/);
 assert.match(app, /'settlement-review':<SettlementReview\/>/);
 assert.match(app, /workspaceNav = NBA_RESEARCH_STAGING_ONLY/);
 assert.match(app, /nav\.filter\(item => item\.id === 'nba-research'\)/);
});

test('manual publication refuses unapproved source coverage',()=>{
 assert.match(app, /!preview\?\.data\?\.publish_ready\|\|uncertain/);
 assert.match(app, /if\(!preview\.data\.publish_ready\)throw Error/);
 assert.match(app, /manual_review_override:manualReview/);
 assert.match(app, /manual_review_reason:manualReason\.trim\(\)/);
});

test('source proposals and explicit confirmations use authorized same-origin proxy',()=>{
 for(const route of [
   'manual-tiers/settlement-review',
   'manual-tiers/settlement-review/propose',
   'manual-tiers/settlement-review/approve',
 ]) assert.ok(proxy.includes("'"+route+"'"));
 assert.match(desk, /api<Queue>\('manual-tiers\/settlement-review\?limit=1000'\)/);
 assert.match(desk, /confirmed_event_id:confirmation/);
 assert.match(desk, /attest_regulation_90:attested/);
 assert.match(desk, /confirmation!==selected\.event_id/);
 assert.match(desk, /booking codes and model results are changed/);
});
