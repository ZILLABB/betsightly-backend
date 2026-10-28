import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const components = readFileSync(new URL('../src/PremiumComponents.tsx', import.meta.url), 'utf8');
const jackpot = readFileSync(new URL('../src/PrivateJackpot.tsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');

test('premium command palette supports keyboard navigation and explicit selection', () => {
  assert.match(app, /event\.ctrlKey\|\|event\.metaKey/);
  assert.match(app, /AdminCommandPalette open=\{commandOpen\}/);
  assert.match(components, /aria-modal="true"/);
  assert.match(components, /event\.key==='ArrowDown'/);
  assert.match(components, /event\.key==='ArrowUp'/);
  assert.match(components, /event\.key==='Enter'/);
});

test('overview does not fabricate trends or backend claims', () => {
  assert.match(app, /PremiumOperationsOverview totals=\{totals\}/);
  assert.match(components, /Counts reflect independent recorded actions/);
  assert.match(components, /statusKnown\?String\(report\.status\)/);
  assert.doesNotMatch(components, /Math\.random/);
});

test('manual publishing requires review and remains blocked after uncertain save', () => {
  assert.match(app, /<AdminActionDialog open=\{publishReview\}/);
  assert.match(app, /disabled=\{!ready\|\|!preview\?\.data\?\.publish_ready\|\|uncertain\}/);
  assert.match(app, /manual_review_override:manualReview/);
  assert.match(app, /if\(!preview\.data\.publish_ready\)throw Error/);
  assert.match(app, /if\(uncertain\)throw Error/);
  assert.match(app, /bs_admin_uncertain/);
  assert.match(app, /persisted\.share_code===result\.share_code/);
  assert.doesNotMatch(app, /window\.confirm\('Publish '/);
});

test('the bookmaker only releases a code after full readback', () => {
  assert.match(jackpot, /result\.readback_status!=='PASSED'/);
  assert.match(jackpot, /pasteReport\.full_ticket_complete===true/);
  assert.match(jackpot, /busyLatch\.current/);
});

test('premium layout maintains keyboard and reduced-motion accessibility', () => {
  assert.match(css, /premium-command-dialog/);
  assert.match(css, /premium-bento-metrics/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /prefers-reduced-motion:reduce/);
});
