#!/usr/bin/env python3
"""One-time read-only probe of SportyBet's undocumented football result feed.

Runs only in isolated GitHub Actions; does not post credentials, loop/retry,
download entire fixture boards, or publish/settle any BetSightly outcomes.
"""
import json
from datetime import datetime, timezone

import requests

day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
url = "https://www.sportybet.com/api/ng/factsCenter/eventResultList"
try:
    r = requests.get(
        url, params={"sportId": "sr:sport:1", "date": day,
                     "pageNum": 1, "pageSize": 10},
        headers={"Accept": "application/json"}, timeout=10,
    )
    print("HTTP_STATUS", r.status_code)
    print("CONTENT_TYPE", r.headers.get("Content-Type", "")[:80])
    if r.status_code != 200:
        print("RESULT", "unavailable")
    else:
        try:
            payload = r.json()
        except ValueError:
            print("RESULT", "non_json")
        else:
            if isinstance(payload, dict):
                print("TOP_KEYS", json.dumps(sorted(payload.keys())[:16]))
                print("BIZ_CODE", repr(payload.get("bizCode")))
                data = payload.get("data")
                print("DATA_TYPE", type(data).__name__)
                if isinstance(data, dict):
                    print("DATA_KEYS", json.dumps(sorted(data.keys())[:20]))
                    for key in ("tournaments", "events", "results", "matches"):
                        v = data.get(key)
                        if isinstance(v, list):
                            print(key.upper()+"_COUNT", len(v))
                            if v and isinstance(v[0], dict):
                                print(key.upper()+"_ITEM_KEYS", json.dumps(sorted(v[0].keys())[:25]))
                                if key == "tournaments":
                                    for evkey in ("events", "matches", "results"):
                                        ev = v[0].get(evkey)
                                        if isinstance(ev, list) and ev:
                                            print("EVENT_FIELDS", json.dumps(sorted(ev[0].keys())[:35]))
            else:
                print("RESULT", "unsupported_json")
except requests.RequestException as exc:
    print("RESULT", "network_error", type(exc).__name__)
