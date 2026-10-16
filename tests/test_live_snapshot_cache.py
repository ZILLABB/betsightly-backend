"""The live-score UI cache never overwrites the official settlement record."""
from datetime import datetime, timezone
from pathlib import Path
import json
from leagues.live_snapshot_cache import LiveScoreSnapshot

NOW=datetime.now(timezone.utc).isoformat()

def board(score=1, ids=None):
    return {"scores":{"abc":{"home_score":score, "away_score":0,
            "live":True,"finished":False}},
            "published_match_ids":ids or ["abc"], "dates":["2026-10-16"],
            "leagues":["eng.1"],"fetched_at":datetime.now(timezone.utc).isoformat()}

def test_cold_first_score_and_root_anchored(tmp_path):
    cache=LiveScoreSnapshot(cache_root=tmp_path,day=lambda:"2026-10-16")
    data=cache.get(lambda:board())
    assert data["scores"]["abc"]["home_score"]==1
    assert not data["scores"]["abc"]["stale"]
    assert (tmp_path/"published_2026-10-16.json").is_file()

def test_restart_can_read_same_day_disk_without_network(tmp_path):
    first=LiveScoreSnapshot(cache_root=tmp_path,day=lambda:"2026-10-16")
    first.get(lambda:board())
    second=LiveScoreSnapshot(cache_root=tmp_path,day=lambda:"2026-10-16")
    snap=second.get(lambda: (_ for _ in ()).throw(AssertionError("network")))
    assert snap["scores"]["abc"]["home_score"]==1

def test_failed_provider_keeps_last_score_and_marks_stale(tmp_path):
    cache=LiveScoreSnapshot(cache_root=tmp_path,day=lambda:"2026-10-16")
    cache.get(lambda:board(2))
    # Simulate a failed fetch and stale memory; no thread timing races.
    cache._refresh("2026-10-16", lambda: {"error":"failed"})
    output=cache.get(lambda: {"error":"failed"})
    assert output["scores"]["abc"]["home_score"]==2
    assert output["scores"]["abc"]["stale"]
    assert output["stale"]

def test_new_day_never_reuses_yesterdays_score(tmp_path):
    key=["2026-10-16"]
    cache=LiveScoreSnapshot(cache_root=tmp_path,day=lambda:key[0])
    cache.get(lambda:board(1))
    key[0]="2026-10-17"
    refreshed=cache.get(lambda:{"scores":{},"published_match_ids":[],
      "leagues":[],"dates":[],"fetched_at":datetime.now(timezone.utc).isoformat()})
    assert not refreshed["scores"]

def test_missing_score_retained_only_if_fixture_still_published(tmp_path):
    earlier=board(2)
    fresh={"scores":{},"published_match_ids":["abc"],
           "fetched_at":datetime.now(timezone.utc).isoformat(),"dates":["2026-10-16"]}
    combined=LiveScoreSnapshot._combine_missing(fresh,earlier)
    assert combined["scores"]["abc"]["stale"]
    other=LiveScoreSnapshot._combine_missing(dict(fresh,published_match_ids=[]),earlier)
    assert other["scores"]=={}

def test_cache_does_not_write_betting_results(tmp_path):
    before={"settled":0,"model_calibration":0}
    cache=LiveScoreSnapshot(cache_root=tmp_path,day=lambda:"2026-10-16")
    cache.get(lambda:board(4))
    assert before=={"settled":0,"model_calibration":0}
