# BetSightly Historical Coverage Gap Audit

Generated: `2026-09-27T11:07:14.760048+00:00`

Read-only audit. No data was downloaded, rewritten, or used to retrain models.

## Snapshot

- Live target league IDs: **33**
- Current training league IDs: **29**
- Missing live target IDs: `[1, 2, 3, 11, 13, 265, 292, 307, 848]`
- Existing GitHub-history file available: **True**
- Existing GitHub-history rows inspected: **228,377**
- Existing GitHub-history divisions: **38**

## Missing competition review

### 1 — FIFA World Cup

Local source status: **NO_LOCAL_CANDIDATE**

No plausible local division label was found.

### 2 — UEFA Champions League

Local source status: **NO_LOCAL_CANDIDATE**

No plausible local division label was found.

### 3 — UEFA Europa League

Local source status: **NO_LOCAL_CANDIDATE**

No plausible local division label was found.

### 11 — Copa Sudamericana

Local source status: **NO_LOCAL_CANDIDATE**

No plausible local division label was found.

### 13 — Copa Libertadores

Local source status: **NO_LOCAL_CANDIDATE**

No plausible local division label was found.

### 265 — Chilean Primera Division

Local source status: **NO_LOCAL_CANDIDATE**

No plausible local division label was found.

### 292 — K League 1

Local source status: **NO_LOCAL_CANDIDATE**

No plausible local division label was found.

### 307 — Saudi Pro League

Local source status: **NO_LOCAL_CANDIDATE**

No plausible local division label was found.

### 848 — UEFA Conference League

Local source status: **NO_LOCAL_CANDIDATE**

No plausible local division label was found.

## Interpretation rule

- `STRONG_LOCAL_CANDIDATE`: likely already present locally, but still requires an explicit division-to-competition mapping before ingestion.
- `POSSIBLE_LOCAL_CANDIDATE`: useful lead; inspect before mapping.
- `FUZZY_REVIEW_REQUIRED`: do not ingest automatically.
- `NO_LOCAL_CANDIDATE`: likely needs another verified free source.
- `FILE_MISSING`: local 228K source is unavailable in this worktree.

No candidate found by this audit is automatically treated as canonical coverage.
