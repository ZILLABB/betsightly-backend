"""No bookmaker scoreboard observation may change official settlement."""
from copy import deepcopy
from services import sportybet_result_source as source

DAY = "2026-10-16"
PICK = {
    "sportybet_event_id": "sr:match:12345678",
    "home_team": "Alpha", "away_team": "Beta",
    "commence_time": "2026-10-16T18:00:00Z",
}
def final(status="FT", home=2, away=1, **kwargs):
    return {"eventId": "sr:match:12345678",
            "homeTeamName": "Alpha", "awayTeamName": "Beta",
            "estimateStartTime": 1792173600000,
            "matchStatus": status,
            "homeScore": home, "awayScore": away, **kwargs}


def test_only_explicit_full_time_is_parsed():
    assert source.parse_final(final(status="1H")) is None
    assert source.parse_final(final(status="HT")) is None
    assert source.parse_final(final(status="2H")) is None
    assert source.parse_final(final(status="PEN")) is None
    assert source.parse_final(final(status="POSTPONED")) is None
    assert source.parse_final(final(status="FT")) is not None


def test_incomplete_scores_and_extra_time_are_not_regulation_finals():
    assert source.parse_final(final(home=None)) is None
    assert source.parse_final(final(extraTimeScore={"home": 3, "away": 2})) is None
    assert source.parse_final(final(score90={"home": 2, "away": 1},
                                    extraTimeScore={"home": 3, "away": 2}))["home_score"] == 2


def test_reconcile_exact_event_home_away_and_date_only():
    official = {"alpha|beta|2026-10-16": {"home_score": 2, "away_score": 1}}
    immutable = deepcopy(official)
    norm = lambda s: str(s).lower()
    lookup = lambda scores, home, away, date: scores.get(home.lower()+"|"+away.lower()+"|"+date)
    report = source.reconcile([PICK], [final()], official, normalize=norm, lookup=lookup)
    assert report["matched"] == report["agreements"] == 1
    assert official == immutable
    wrong_team = final(awayTeamName="Gamma")
    assert source.reconcile([PICK], [wrong_team], official, normalize=norm, lookup=lookup)["matched"] == 0
    wrong_id = final(eventId="sr:match:999")
    assert source.reconcile([PICK], [wrong_id], official, normalize=norm, lookup=lookup)["matched"] == 0
    wrong_day = final(estimateStartTime=1792087200000)
    assert source.reconcile([PICK], [wrong_day], official, normalize=norm, lookup=lookup)["matched"] == 0


def test_score_conflicts_are_diagnostics_not_settlement():
    official = {"alpha|beta|2026-10-16": {"home_score": 2, "away_score": 1}}
    norm=lambda s:str(s).lower()
    lookup=lambda scores,h,a,d:scores.get(h.lower()+"|"+a.lower()+"|"+d)
    report=source.reconcile([PICK],[final(home=0,away=4)],official,normalize=norm,lookup=lookup)
    assert report["disagreements"]==1
    assert official["alpha|beta|2026-10-16"]["home_score"]==2


def test_disabled_by_default_never_calls_bookmaker(monkeypatch):
    monkeypatch.delenv("SPORTYBET_RESULTS_SHADOW_ENABLED",raising=False)
    monkeypatch.setattr(source.requests,"get",lambda *a,**kw: (_ for _ in ()).throw(AssertionError("network")))
    assert source.observe([PICK],{} )["mode"]=="shadow_only"


def test_unexpected_response_fails_closed(monkeypatch):
    monkeypatch.setenv("SPORTYBET_RESULTS_SHADOW_ENABLED","true")
    monkeypatch.setattr(source,"_LAST_FETCH",0)
    class Response:
        status_code=200
        def json(self):return {"bizCode":10000,"data":{"tournaments":[]}}
    monkeypatch.setattr(source.requests,"get",lambda *a,**kw:Response())
    report=source.observe([PICK],{})
    assert report["observed"]==report["matched"]==0
    assert report["status"]=="read_only_observation"
