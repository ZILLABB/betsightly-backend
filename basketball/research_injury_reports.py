"""Official NBA injury report snapshot archive — never retroactively labeled.

The official page lists PDF versions which can change every 15 minutes. A
snapshot's *publication time* is derived from the report filename in
America/New_York, never the local fetch time; the archive is append-only.
Parsing is intentionally fail-closed and reports partial/unmatched content.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.error import URLError,HTTPError
from urllib.parse import urljoin,urlsplit
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo

REPORT_PAGE="https://official.nba.com/nba-injury-report-2026-27-season/"
PDF_PREFIX="https://ak-static.cms.nba.com/referee/injury/"
FILENAME=re.compile(r"^Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf$",re.I)
MAX_PDF=5_000_000
MAX_PAGE=1_000_000
ALLOWED={"Out","Doubtful","Questionable","Probable","Available"}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()!="a":return
        d=dict(attrs)
        href=d.get("href")
        if href:self.urls.append(href)


def _datetime_from_name(url:str)->datetime|None:
    parsed=urlsplit(url)
    if parsed.scheme!="https" or parsed.netloc!="ak-static.cms.nba.com":
        return None
    if not parsed.path.startswith("/referee/injury/"):
        return None
    match=FILENAME.fullmatch(parsed.path.rsplit("/",1)[-1])
    if not match:return None
    day,hh,mm,ampm=match.groups()
    h=int(hh)
    if not 1<=h<=12 or int(mm)>59:return None
    hour=h%12+(12 if ampm.upper()=="PM" else 0)
    try:
        local=datetime.fromisoformat(f"{day}T{hour:02d}:{mm}:00").replace(
            tzinfo=ZoneInfo("America/New_York"))
        return local.astimezone(timezone.utc)
    except ValueError:
        return None


def select_report(html:str,*,now:datetime,day:str|None=None)->dict:
    if now.tzinfo is None:raise ValueError("Need timezone-aware clock")
    links=_Links()
    links.feed(html)
    chosen=[]
    for link in links.urls:
        uri=urljoin(REPORT_PAGE,link)
        published=_datetime_from_name(uri)
        if published is None or published>now.astimezone(timezone.utc):
            continue
        if day and published.astimezone(ZoneInfo("America/New_York")).date().isoformat()!=day:
            continue
        chosen.append((published,uri))
    if not chosen:
        raise ValueError("No valid already published official injury PDF link")
    published,uri=max(chosen,key=lambda item:item[0])
    return {
        "source_url":uri,"published_at":published.isoformat(),
        "source":"nba:official_injury_report_pdf:v1",
    }


def _bounded(url:str,limit:int,*,opener=urlopen)->bytes:
    req=Request(url,headers={
        "User-Agent":"BetSightlyNBAResearch/1.0",
        "Accept":"application/pdf,text/html;q=0.8",
    })
    try:
        with opener(req,timeout=25) as r:
            if int(r.headers.get("Content-Length") or 0)>limit:
                raise ValueError("Official NBA report exceeds byte budget")
            raw=r.read(limit+1)
    except (URLError,HTTPError,TimeoutError) as exc:
        raise RuntimeError("Official NBA injury source temporarily unavailable") from exc
    if len(raw)>limit or len(raw)<30:
        raise ValueError("Incomplete or oversized official NBA injury response")
    return raw


def parse_pdf_players(data:bytes)->tuple[list[dict],dict]:
    """Best-effort exact-column extraction; no guessed names or statuses.

    With unreadable PDF table structure, an empty list and explicit
    extraction warning are returned. No injury data enters any model.
    """
    try:
        import pdfplumber
    except ImportError:
        return [],{"status":"unparsed","reason":"pdfplumber_not_installed",
                   "recognized_player_rows":0}
    if not data.startswith(b"%PDF-"):
        raise ValueError("Injury report is not a valid PDF envelope")
    entries=[]
    incomplete=0
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            if len(pdf.pages)>30:raise ValueError("Injury report exceeds page budget")
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table:continue
                    header=[str(c or "").strip().lower().replace("\n"," ")
                            for c in table[0]]
                    def col(token):
                        return next((i for i,x in enumerate(header) if token in x),None)
                    t,p,s=col("team"),col("player name"),col("current status")
                    if None in (t,p,s):continue
                    last_team=None
                    for row in table[1:]:
                        if len(row)<=max(t,p,s):continue
                        team=str(row[t] or "").replace("\n"," ").strip()
                        if team:last_team=team
                        name=str(row[p] or "").replace("\n"," ").strip()
                        status=str(row[s] or "").replace("\n"," ").strip()
                        if not name and status.upper()=="NOT YET SUBMITTED":
                            incomplete+=1
                            continue
                        if (not last_team or not name or status not in ALLOWED):
                            continue
                        if len(name)>120 or len(last_team)>120:continue
                        entries.append({
                            "team":last_team,"player":name,
                            "status":status,
                            "as_reported":True,
                        })
    except (ValueError,TypeError,AttributeError) as exc:
        return [],{"status":"unparsed","reason":"pdf_layout_not_verified",
                   "recognized_player_rows":0}
    de_duped={(r["team"],r["player"]):r for r in entries}
    return list(de_duped.values()),{
        "status":"parsed" if de_duped else "unparsed",
        "reason":None if de_duped else "no_exact_column_rows",
        "recognized_player_rows":len(de_duped),
        "teams_not_yet_submitted":incomplete,
        "partial_report_possible":True,
    }


def capture_injury(home:str|Path,*,now:datetime|None=None,day:str|None=None,
                   opener=urlopen,parser=parse_pdf_players)->dict:
    timestamp=now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:raise ValueError("Timezone-aware clock required")
    html=_bounded(REPORT_PAGE,MAX_PAGE,opener=opener).decode("utf-8")
    meta=select_report(html,now=timestamp,day=day)
    data=_bounded(meta["source_url"],MAX_PDF,opener=opener)
    if not data.startswith(b"%PDF-"):raise ValueError("Official injury link returned non-PDF bytes")
    digest=hashlib.sha256(data).hexdigest()
    published=datetime.fromisoformat(meta["published_at"])
    if published>timestamp.astimezone(timezone.utc):
        raise ValueError("An injury snapshot cannot originate in the future")
    rows,extraction=parser(data)
    root=Path(home)/"injuries"
    root.mkdir(parents=True,exist_ok=True)
    stamp=published.strftime("%Y%m%dT%H%M%SZ")
    original=root/f"{stamp}-{digest[:12]}.pdf"
    manifest=root/f"{stamp}-{digest[:12]}.json"
    # Files are immutable, addressable by both publication time and SHA.
    if original.exists():
        if hashlib.sha256(original.read_bytes()).hexdigest()!=digest:
            raise ValueError("Stored injury report hash conflict")
    else:
        tmp=original.with_suffix(".pdf.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp,original)
        finally:
            if tmp.exists():tmp.unlink()
    result={
        **meta,"sha256":digest,"file":original.name,
        "downloaded_at":timestamp.astimezone(timezone.utc).isoformat(),
        "parsed_player_rows":rows,"extraction":extraction,
        "pregame_use_enabled":False,
        "player_identifier_crosswalk_verified":False,
        "research_only":True,"commercial_use_review_required":True,
    }
    if not manifest.exists():
        tmp=manifest.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
            os.replace(tmp,manifest)
        finally:
            if tmp.exists():tmp.unlink()
    return {
        "status":"archived","published_at":meta["published_at"],
        "snapshot_hash":digest,"player_rows":len(rows),
        "extraction":extraction,"archive_file":str(original),
        "no_historical_backfill":True,"pregame_model_integration":False,
        "research_only":True,
    }


def injury_status(home:str|Path)->dict:
    root=Path(home)/"injuries"
    files=sorted(root.glob("*.json"),reverse=True)
    if not files:
        return {"status":"not_observed","latest_published_at":None,
                "snapshots":0,"pregame_model_integration":False}
    latest=json.loads(files[0].read_text(encoding="utf-8"))
    return {
        "status":latest.get("extraction",{}).get("status","archived"),
        "latest_published_at":latest.get("published_at"),
        "snapshots":len(files),
        "player_rows":len(latest.get("parsed_player_rows") or []),
        "teams_not_submitted":latest.get("extraction",{}).get(
            "teams_not_yet_submitted"),
        "pregame_model_integration":False,
        "commercial_use_review_required":True,
    }
