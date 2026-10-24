"""Atlantic-themed read-only NBA paper research view; loopback only.

Starts only from the explicit CLI 'dashboard' command. The production app
never imports or mounts it. No bets, odds, user data or publishing controls.
"""
from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from basketball.research_readiness import readiness_from_home
from basketball.research_prospective import prospective_report
from basketball.research_operations import operations_from_home
from basketball.research_automation import reliability_from_home
from basketball.research_store import (
    DEFAULT_DB, latest_events, list_forecasts, open_ledger,
    performance_report,
)


def _safe(value: object) -> str:
    return html.escape(str(value if value is not None else "—"), quote=True)


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{100*value:.1f}%"


def render_dashboard(report: dict, forecasts: list[dict],
                     events: list[dict], readiness: dict | None = None,
                     prospective: dict | None = None,
                     operations: dict | None = None,
                     reliability: dict | None = None) -> str:
    """Server-rendered and escaped HTML, no tracking or external dependencies."""
    metric = lambda name, value, note: (
        '<div class="metric"><small>' + _safe(name) + '</small>'
        '<strong>' + _safe(value) + '</strong><span>' + _safe(note) + '</span></div>'
    )
    metrics = "".join([
        metric("PAPER FORECASTS", report["forecast_count"], "Immutable original picks"),
        metric("VERIFIED FINALS", report["settled"], "Matched with exact fixture IDs"),
        metric("PENDING", report["pending"], "Not yet finally settled"),
        metric("WIN ACCURACY", _percent(report.get("accuracy")), "Paper only · no ROI"),
        metric("BRIER SCORE", report.get("brier", "—"), "Lower is better"),
        metric("LOG LOSS", report.get("log_loss", "—"), "Lower is better"),
    ])
    if report.get("score_projections"):
        scores = report["score_projections"]
        metrics += metric("TOTAL-POINTS MAE", scores.get("total_points_mae"),
                          "Prospective paper score errors")
        metrics += metric("POINT-MARGIN MAE", scores.get("home_margin_mae"),
                          "Not bookmaker spread results")
    rows = []
    for row in forecasts:
        finished = row["recorded_at"] is not None
        label = "SETTLED" if finished else "AWAITING RESULT"
        correct = ("YES" if (row["home_win_probability"] >= .5) ==
                   bool(row["home_won"]) else "NO") if finished else "—"
        score = (f'{row["home_score"]} : {row["away_score"]}'
                 if finished else "Pending")
        rows.append(
            "<tr><td><strong>" + _safe(row["home_team"]) +
            "</strong> <span class='muted'>vs</span> " + _safe(row["away_team"]) +
            "<small>" + _safe(row["fixture_date"]) + " · " +
            _safe(row["game_id"]) + "</small></td><td>" +
            _safe(_percent(row["home_win_probability"])) + "</td><td>" +
            _safe(row.get("expected_total_points")) + "</td><td>" +
            _safe(row.get("expected_home_margin")) + "</td><td>" +
            _safe(score) + "</td><td>" + _safe(correct) + "</td><td>" +
            _safe(label) + "</td></tr>"
        )
    # The readiness panel examines source fixtures, not just saved forecasts.
    # All provider-supplied names/reasons are HTML-escaped before rendering.
    readiness_metrics = ""
    ready_rows = []
    overdue_rows = []
    scoreboard_note = "No scoreboard verification cycle has run yet."
    ready_note = "No verified fixture snapshot loaded; run the NBA research cycle."
    if readiness is not None:
        snapshot = readiness["snapshot"]
        age = snapshot.get("age_hours")
        age_label = "—" if age is None else f"{age:.1f}h ago"
        readiness_metrics = "".join([
            metric("UPCOMING FIXTURES", readiness["upcoming_fixtures"],
                   f"Next {readiness['days_ahead']} days"),
            metric("FEATURE-READY", readiness["feature_ready"],
                   "Both teams have >=5 earlier finals"),
            metric("READY FOR PAPER", readiness["eligible_forecasts"],
                   "Pregame, fresh source and local model"),
            metric("STARTED · UNVERIFIED", readiness["started_unverified"],
                   "Past 72h, no confirmed final in local snapshot"),
            metric("SOURCE HEALTH", snapshot["status"].upper(), age_label),
        ])
        ready_note = (
            "Last data retrieval: " +
            str(snapshot.get("last_retrieved_at") or "not available") +
            ". Source: " + ", ".join(snapshot.get("source") or ["not available"]) +
            ". A stale/invalid snapshot blocks readiness; refresh using the "
            "local cycle. No bookmaker prices or betting signals are used."
        )
        scoreboard = readiness.get("scoreboard")
        if scoreboard:
            scoreboard_note = (
                "Recent score checks: " + str(scoreboard.get("status", "unknown")) +
                " · Last checked: " + str(scoreboard.get("checked_at", "—")) +
                " · Verified new finals: " +
                str(scoreboard.get("verified_new_finals", 0)) +
                " · Failed dates: " +
                str(len(scoreboard.get("failed_dates") or [])) +
                ". ESPN's scoreboard feed is unofficial and may be unavailable."
            )
        for game in readiness["fixtures"]:

            codes = game["reasons"]
            reason = ("Eligible for private paper forecasting" if not codes
                      else "; ".join(
                          readiness["reason_labels"].get(code, code)
                          for code in codes))
            target = (overdue_rows if game["fixture_state"] ==
                      "started_unverified" else ready_rows)
            if len(target) >= (20 if target is overdue_rows else 40):
                continue
            target.append(
                "<tr><td><strong>" + _safe(game["home_team"]) +
                "</strong> <span class='muted'>vs</span> " +
                _safe(game["away_team"]) + "<small>" +
                _safe(game["date"]) + " · " +
                _safe(game["game_id"]) + "</small></td><td>" +
                _safe(game["start_utc"]) + "</td><td>" +
                _safe(game["home_prior_games"]) + " / 5</td><td>" +
                _safe(game["away_prior_games"]) + " / 5</td><td>" +
                _safe("READY" if game["eligible"] else "BLOCKED") +
                "</td><td>" + _safe(reason) + "</td></tr>"
            )
    operations_metrics = ""
    operations_note = (
        "First-forecast operational monitor unavailable; refresh the local "
        "research snapshot and check the read-only operations command."
    )
    ops_rows = []
    if operations is not None:
        cycle = operations.get("daily_cycle") or {}
        operations_metrics = "".join([
            metric("STAGE 2D STATE",
                   operations.get("operational_state", "unknown").upper(),
                   "Local first-forecast milestone"),
            metric("READY IN DAILY WINDOW",
                   operations.get("eligible_in_daily_cycle_window", "—"),
                   "Provider dates today and tomorrow"),
            metric("PAPER FORECASTS SAVED",
                   operations.get("total_recorded_paper_forecasts", "—"),
                   "Original immutable private records"),
            metric("OVERDUE PENDING",
                   len(operations.get("overdue_pending", [])),
                   "More than four hours after tipoff"),
            metric("DAILY CYCLE",
                   cycle.get("status", "not_seen").upper(),
                   "Last detected: " + str(cycle.get("last_seen_at") or "—")),
        ])
        warnings = operations.get("warnings") or []
        operations_note = (
            "Next: " + operations.get("next_step", "review lab health") +
            ". Warnings: " + (", ".join(warnings) if warnings else "none") +
            ". A missing forecast is not a loss and cannot be backfilled."
        )
        for item in operations.get("eligible_not_yet_recorded", [])[:20]:
            ops_rows.append(
                "<tr><td>" + _safe(item["home_team"]) +
                " <span class='muted'>vs</span> " +
                _safe(item["away_team"]) + "</td><td>" +
                _safe(item["game_id"]) + "</td><td>" +
                _safe(item["start_utc"]) + "</td><td>" +
                "Eligible, not yet recorded</td></tr>"
            )
    reliability_metrics = ""
    reliability_note = ("New Stage 2E scheduled-job health receipts not found. "
                        "Run a private automated job before interpreting task health.")
    if reliability is not None:
        statuses = reliability.get("tasks") or {}
        reliability_metrics = "".join(
            metric("AUTOMATED " + mode.upper(),
                   (statuses.get(mode) or {}).get("status", "not_observed").upper(),
                   "Task health · last check: " +
                   str((statuses.get(mode) or {}).get("last_seen_at") or "—"))
            for mode in ("pregame", "score", "full")
        )
        issues = reliability.get("issues") or []
        reliability_note = (
            "Task failures/staleness: " +
            (", ".join(issues) if issues else "none detected") +
            ". An unobserved task is not a successful run; the Windows "
            "computer must be awake for scheduled checks."
        )
    # A prospective cohort uses only the privately settled pregame ledger.
    # Historical validation metrics are never mixed into this panel.
    evaluation_metrics = ""
    evaluation_note = (
        "No saved prospective evaluation yet. Once the five-game warm-up "
        "finishes, the private 18:00 WAT cycle can record real pregame forecasts."
    )
    calibration_rows = []
    if prospective is not None:
        status = prospective["status"]
        if status == "integrity_failed":
            evaluation_note = (
                "Integrity warning: stored prediction hashes/timing/scores "
                "failed validation. Prospective metrics are withheld. " +
                str(prospective.get("issue_count", 0)) +
                " records need investigation. Do not publish performance claims."
            )
        elif status != "awaiting_first_forecast":
            count = prospective.get("settled_count", 0)
            overall = prospective.get("overall") or {}
            score = prospective.get("score_projection_errors") or {}
            review = prospective.get("sample_size_gate_met", False)
            evaluation_metrics = "".join([
                metric("SETTLED PAPER GAMES", count, "Real prospective results only"),
                metric("FIXED 50/50 BRIER", "0.2500",
                       "Predeclared probability baseline"),
                metric("MODEL BRIER", overall.get("brier", "—"),
                       "Lower is better; sample gated"),
                metric("BRIER SKILL", overall.get("brier_skill_vs_50_50", "—"),
                       "Positive beats fixed 50/50 baseline"),
                metric("TOTAL POINTS MAE", score.get("total_points_mae", "—"),
                       "Mean absolute error in points"),
                metric("HOME MARGIN MAE", score.get("home_margin_mae", "—"),
                       "Mean absolute error in points"),
            ])
            evaluation_note = (
                f"{count}/{prospective['review_minimum_settled']} settled "
                "prospective forecasts for the first descriptive review. " +
                ("Review threshold met; this is NOT proof of profitability."
                 if review else
                 "Early results are unstable and do not establish quality.") +
                " No verified bookmaker odds or betting ROI."
            )
            for bucket in prospective["calibration"]["bins"]:
                label = f"{bucket['lower']:.0%}–{bucket['upper']:.0%}"
                calibration_rows.append(
                    "<tr><td>" + _safe(label) + "</td><td>" +
                    _safe(bucket["count"]) + "</td><td>" +
                    _safe(_percent(bucket["average_forecast"])) +
                    "</td><td>" +
                    _safe(_percent(bucket["observed_home_win"])) +
                    "</td><td>" +
                    _safe("Too small to interpret" if bucket["descriptive_only"]
                          else "Descriptive") + "</td></tr>"
                )
    history_rows = "".join(
        "<li><time>" + _safe(event["occurred_at"]) + "</time> " +
        _safe(event["kind"]) + ": " + _safe(event["message"]) + "</li>"
        for event in events
    )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="referrer" content="no-referrer">
<title>BetSightly · NBA Research</title>
<style>
:root{color-scheme:dark;--bg:#061522;--panel:#0e2639;--border:#244457;
 --text:#eff7fb;--muted:#9db8c6;--accent:#59e4d0}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at
 80% 0%,#10425c 0,#061522 46%);color:var(--text);
 font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1250px;margin:0 auto;padding:35px 22px 80px}
header{display:flex;justify-content:space-between;align-items:center;gap:20px;
 padding-bottom:28px;border-bottom:1px solid var(--border);flex-wrap:wrap}
.brand{font-size:17px;font-weight:750;letter-spacing:.14em}.brand b{color:var(--accent)}
.tag{display:inline-block;border:1px solid #326779;border-radius:50px;
 padding:6px 12px;font-size:11px;letter-spacing:.12em;color:var(--accent)}
h1{font-size:clamp(30px,5vw,52px);letter-spacing:-.045em;line-height:1.1;
 margin:34px 0 12px}h2{font-size:18px;margin:38px 0 16px}
p{color:var(--muted);max-width:750px}.stats{display:grid;
 grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:13px;margin:28px 0}
.metric,.panel{border:1px solid var(--border);background:linear-gradient(
 150deg,rgba(20,55,77,.91),rgba(8,31,48,.94));border-radius:16px;padding:22px}
.metric small{font-size:10px;color:var(--accent);letter-spacing:.12em;
 font-weight:750}.metric strong{display:block;font-size:32px;margin:5px 0}
.metric span,.muted{color:var(--muted)}.metric span{font-size:12px}
.panel{overflow-x:auto}table{border-collapse:collapse;width:100%;text-align:left;
 min-width:660px}th{font-size:11px;letter-spacing:.09em;color:var(--muted);
 padding:12px;border-bottom:1px solid var(--border)}td{padding:15px 12px;
 border-bottom:1px solid #224055;font-size:13px}td small{display:block;
 color:var(--muted);font-size:11px;margin-top:4px}
.notice{border-left:3px solid var(--accent);padding:14px 18px;
 background:rgba(89,228,208,.07);border-radius:8px;color:#cdeee8}
ul{padding:0;list-style:none;margin:0}li{padding:12px 0;border-bottom:
 1px solid var(--border);font-size:12px;color:var(--muted)}
time{color:var(--accent)}footer{margin-top:40px;color:var(--muted);font-size:11px}
</style></head><body><main>
<header><div class="brand">BET<b>SIGHTLY</b> <span class="muted">/ LABS</span></div>
<span class="tag">PRIVATE · OFFLINE · NO BETTING</span></header>
<h1>Basketball research,<br>without the guesswork.</h1>
<p>A local-only Atlantic command center. Every paper prediction is captured
before tip-off and can only be settled against verified final scores.
No actual bookmaker prices, codes or stakes are accepted.</p>
<div class="notice">This is an internal experiment—not a live service or
evidence of profitable betting. Historical model accuracy is not a wagering
return. The public BetSightly app remains separate.</div>
<section class="stats">""" + metrics + """</section>
<h2>Upcoming NBA readiness</h2>
<p>Fixtures are scored for eligibility without generating or editing a forecast.
Only earlier completed regular-season games in the same season count.</p>
<section class="stats">""" + readiness_metrics + """</section>
<div class="notice">""" + _safe(ready_note) + """</div>
<div class="notice">""" + _safe(scoreboard_note) + """</div>
<div class="panel"><table>
<thead><tr><th>NBA fixture</th><th>Start (UTC)</th><th>Home prior</th>
<th>Away prior</th><th>Readiness</th><th>Why</th></tr></thead><tbody>""" + (
    "".join(ready_rows) if ready_rows else
    "<tr><td colspan='6'>No upcoming scheduled fixtures in the selected "
    "horizon. Inspect source health and the next data refresh.</td></tr>"
) + """</tbody></table></div>
<h2>Started, awaiting verified final</h2>
<p>Games that have passed their scheduled tipoff in the past 72 hours but
still lack an accepted final score. They are never pregame candidates.</p>
<div class="panel"><table>
<thead><tr><th>NBA fixture</th><th>Tipoff (UTC)</th><th>Home prior</th>
<th>Away prior</th><th>Status</th><th>Why</th></tr></thead><tbody>""" + (
    "".join(overdue_rows) if overdue_rows else
    "<tr><td colspan='6'>No started-but-unverified games in the last 72h.</td></tr>"
) + """</tbody></table></div>
<h2>Stage 2E · automation reliability</h2>
<p>Separate recorded outcomes for the pregame, score and daily jobs.
A skipped overlapping run never changes a forecast or final score.</p>
<section class="stats">""" + reliability_metrics + """</section>
<div class="notice">""" + _safe(reliability_note) + """</div>
<h2>First-forecast operations</h2>
<p>Tracks the first genuine recorded NBA prediction through settlement,
without backfilling or making synthetic picks. The 18:00 local Windows
task may be missed while the computer is asleep.</p>
<section class="stats">""" + operations_metrics + """</section>
<div class="notice">""" + _safe(operations_note) + """</div>
<div class="panel"><table><thead><tr>
<th>Eligible NBA fixture</th><th>Fixture ID</th><th>Tipoff (UTC)</th>
<th>Ledger status</th></tr></thead><tbody>""" + (
    "".join(ops_rows) if ops_rows else
    "<tr><td colspan='4'>No eligible, unrecorded games in this daily window.</td></tr>"
) + """</tbody></table></div>
<h2>Prospective research evaluation</h2>
<p>Only forecasts originally saved before tipoff and subsequently settled.
No historical backtests, bookmaker odds, or after-the-fact picks.</p>
<section class="stats">""" + evaluation_metrics + """</section>
<div class="notice">""" + _safe(evaluation_note) + """</div>
<div class="panel"><table>
<thead><tr><th>Home win probability</th><th>Games</th>
<th>Average forecast</th><th>Observed home wins</th><th>Interpretation</th>
</tr></thead><tbody>""" + (
    "".join(calibration_rows) if calibration_rows else
    "<tr><td colspan='5'>No settled prospective calibration data.</td></tr>"
) + """</tbody></table></div>
<h2>Paper prediction ledger</h2><div class="panel"><table>
<thead><tr><th>NBA fixture</th><th>Home ML probability</th>
<th>Expected total</th><th>Expected home margin</th><th>Verified score</th><th>Correct</th><th>Status</th></tr></thead><tbody>""" + (
        "".join(rows) if rows else
        "<tr><td colspan='7'>No eligible pregame paper predictions recorded."
        " The season warm-up gate may still be active.</td></tr>"
    ) + """</tbody></table></div>
<h2>Research activity</h2><div class="panel"><ul>""" + (
        history_rows or "<li>No completed research cycles yet.</li>"
    ) + """</ul></div>
<footer>Localhost only · stored in private SQLite · never uploaded by CI.
Training data access and commercial usage rights still require review.</footer>
</main></body></html>"""


def make_handler(db_path: Path):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Prevent hostile websites from reusing loopback Host headers.
            host = self.headers.get("Host", "").split(":")[0].strip().lower()
            if host not in {"127.0.0.1", "localhost"}:
                self.send_error(403, "Loopback Host only")
                return
            route = urlsplit(self.path).path
            if route not in {"/", "/api/summary", "/api/fixtures",
                             "/api/readiness", "/api/prospective", "/api/operations",
                             "/api/reliability"}:
                self.send_error(404)
                return
            connection = open_ledger(db_path)
            try:
                report = performance_report(connection)
                rows = list_forecasts(connection, 300)
                events = latest_events(connection)
            finally:
                connection.close()
            if route == "/":
                readiness = readiness_from_home(db_path.parent)
                prospective = prospective_report(db_path)
                operations = operations_from_home(db_path.parent)
                reliability = reliability_from_home(db_path.parent)
                payload = render_dashboard(
                    report, rows, events, readiness,
                    prospective, operations, reliability).encode("utf-8")
                mime = "text/html; charset=utf-8"
            else:
                if route == "/api/summary":
                    value = {"performance": report, "research_only": True}
                elif route == "/api/readiness":
                    value = readiness_from_home(db_path.parent)
                elif route == "/api/prospective":
                    value = prospective_report(db_path)
                elif route == "/api/operations":
                    value = operations_from_home(db_path.parent)
                elif route == "/api/reliability":
                    value = reliability_from_home(db_path.parent)
                else:
                    value = {"fixtures": rows, "research_only": True}
                payload = json.dumps(value).encode("utf-8")
                mime = "application/json; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args):
            return  # Avoid saving forecasts/identities to access logs.

    return DashboardHandler


def serve_dashboard(db_path: str | Path = DEFAULT_DB, port: int = 8767):
    """Starts an explicit loopback-only read-only local process."""
    if not 1024 <= port <= 65535:
        raise ValueError("Use a nonprivileged local TCP port")
    server = ThreadingHTTPServer(
        ("127.0.0.1", int(port)), make_handler(Path(db_path))
    )
    print(f"NBA PRIVATE RESEARCH: http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
