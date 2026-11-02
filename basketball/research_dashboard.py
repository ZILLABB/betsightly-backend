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

from basketball.research_store import (
    DEFAULT_DB, latest_events, list_forecasts, open_ledger,
    performance_report,
)


def _safe(value: object) -> str:
    return html.escape(str(value if value is not None else "—"), quote=True)


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{100*value:.1f}%"


def render_dashboard(report: dict, forecasts: list[dict],
                     events: list[dict]) -> str:
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
            if route not in {"/", "/api/summary", "/api/fixtures"}:
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
                payload = render_dashboard(report, rows, events).encode("utf-8")
                mime = "text/html; charset=utf-8"
            else:
                value = ({"performance": report, "research_only": True}
                         if route == "/api/summary"
                         else {"fixtures": rows, "research_only": True})
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
