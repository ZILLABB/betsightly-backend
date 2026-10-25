import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const app=readFileSync(new URL('../src/App.tsx',import.meta.url),'utf8');
const page=readFileSync(new URL('../src/BasketballResearch.tsx',import.meta.url),'utf8');
const proxy=readFileSync(new URL('../api/proxy.js',import.meta.url),'utf8');
const css=readFileSync(new URL('../src/styles.css',import.meta.url),'utf8');

test('NBA research tab is default off, under protected admin session',()=>{
  assert.match(app,/VITE_NBA_RESEARCH_ADMIN_ENABLED === 'true'/);
  assert.match(app,/NBA_RESEARCH_ADMIN_ENABLED \? \[/);
  assert.match(app,/'nba-research':<BasketballResearch\/>/);
  assert.match(app,/session==='guest'/);
  assert.match(app,/id:'manual',label:'Manual SportyBet'/);
});
test('NBA research is strictly GET-only via same origin proxy',()=>{
  assert.match(proxy,/'admin\/nba-research'/);
  assert.match(page,/api<ResearchBoard>\('admin\/nba-research'\)/);
  assert.doesNotMatch(page,/api<ResearchBoard>\('admin\/nba-research',/);
  assert.match(page,/refetchOnWindowFocus:false/);
});
test('no fake bookmaker prices, scores, or original picks',()=>{
  assert.match(page,/board\.bookmaker_verified===false/);
  assert.match(page,/board\.booking_codes_available===false/);
  assert.match(page,/board\.model_promotion_approved===false/);
  assert.match(page,/No SportyBet basketball booking code/);
  assert.doesNotMatch(page,/401909861|236\.6947/);
});
test('honest loading, unavailable data, filtering and copy',()=>{
  assert.match(page,/q\.isPending/);
  assert.match(page,/role="alert"/);
  assert.match(page,/status===503/);
  assert.match(page,/Export CSV/);
  assert.match(page,/Copy games/);
  assert.match(page,/timeZone:'Africa\/Lagos'/);
  assert.match(css,/\.nba-metrics/);
  assert.match(css,/prefers-reduced-motion:reduce/);
});