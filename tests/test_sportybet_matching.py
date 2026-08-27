"""
Fixture matching and margin arithmetic for the SportyBet price adapter.

The tests that matter here are the negative ones. Attaching a price to the
wrong fixture is worse than attaching no price at all — the card would show a
number nobody can bet, sourced from a different match — so most of what
follows checks that plausible-looking pairs are *rejected*.

No network. Every case is a real name or payload shape taken from the live
board, pasted in.
"""

import pytest

from leagues import sportybet as sb


# ── Name normalisation ─────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    # NFKD does not decompose these — they are distinct letters, not accents.
    ("Brøndby IF", "brondby"),
    ("Malmö FF", "malmo"),
    ("Djurgården", "djurgarden"),
    # Parenthetical qualifiers differ between feeds.
    ("Central Córdoba (Santiago del Estero)", "central cordoba"),
    ("Libertad (Ecuador)", "libertad"),
    # Founding years appear on one side only.
    ("SC Verl 1924", "verl"),
    # Brazilian and Argentine state codes are hyphenated or absent.
    ("Coritiba-PR", "coritiba pr"),
    # Club-words carry no identity.
    ("FC Cologne", "cologne"),
    ("Kocaelispor", "kocaelispor"),
])
def test_norm(raw, expected):
    assert sb._norm(raw) == expected


def test_norm_never_empties_a_name():
    """A club whose whole name is club-words keeps them rather than vanishing."""
    assert sb._norm("FC") != ""


# ── Squad identity ─────────────────────────────────────────

@pytest.mark.parametrize("raw,squad", [
    ("Amed Sportif Faaliyetler", ""),
    ("Amed Sportif Faaliyetler U19", "u19"),
    ("Real Madrid U21", "u21"),
    ("Jong KRC Genk", "reserve"),
    ("Bayern Munich II", "reserve"),
    ("Chelsea", ""),
])
def test_squad(raw, squad):
    assert sb._squad(raw) == squad


def test_senior_and_youth_are_different_teams():
    """The bug this prevents: a club's U19 answering to the club's name.

    Both sides normalise to a superset of "amed", so the subset rule matches
    each. Without a squad check the lookup sees two candidates and — correctly
    but uselessly — refuses to price a fixture it could have priced.
    """
    senior, youth = "Amed SFK", "Amed Sportif Faaliyetler U19"
    assert sb._same_team(sb._norm(senior), sb._norm(youth))
    assert sb._squad(senior) != sb._squad(youth)


# ── Team matching ──────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("brondby", "broendby"),        # ø transliterated two ways
    ("hamburg", "hamburger"),       # bounded prefix
    ("djurgarden", "djurgardens"),  # genitive
    ("amed", "amed sportif faaliyetler"),
])
def test_same_team_accepts(a, b):
    assert sb._same_team(a, b)


@pytest.mark.parametrize("a,b", [
    ("everton", "liverpool"),
    ("milan", "inter"),
    ("real madrid", "real sociedad"),
    ("atletico madrid", "atletico mineiro"),
    ("boca juniors", "river plate"),
])
def test_same_team_rejects_different_clubs(a, b):
    assert not sb._same_team(a, b)


def test_prefix_match_is_bounded():
    """A prefix rule loose enough to pair short names would pair wrong ones."""
    assert not sb._token_match("real", "realmadridcastilla")
    assert not sb._token_match("inter", "internacional")


# ── Kickoff guard ──────────────────────────────────────────

def test_kickoff_guard_separates_identically_named_clubs():
    """Arsenal (London) and Arsenal de Sarandi normalise the same.

    Nothing in the strings distinguishes them. Kickoff does.
    """
    entry = {"kickoff_ms": 1787598000000}  # 2026-08-24T19:00:00Z
    assert sb._kickoff_ok(entry, "2026-08-24T19:00:00Z")
    assert not sb._kickoff_ok(entry, "2026-08-24T22:00:00Z") # outside strict tolerance
    assert not sb._kickoff_ok(entry, "2026-08-27T15:00:00Z")  # different match


def test_kickoff_guard_rejects_missing_or_bad_data():
    """Missing timestamps cannot silently bypass fixture identity."""
    assert not sb._kickoff_ok({"kickoff_ms": None}, "2026-08-24T19:00:00Z")
    assert not sb._kickoff_ok({"kickoff_ms": 1787598000000}, "")
    assert not sb._kickoff_ok({"kickoff_ms": 1787598000000}, "not-a-date")


# ── Margin arithmetic ──────────────────────────────────────

def _event(markets):
    return {"eventId": "sr:match:1", "homeTeamName": "Home FC",
            "awayTeamName": "Away FC", "estimateStartTime": 1787598000000,
            "markets": markets}


def test_margin_on_a_two_way_market():
    ev = _event([{"id": "18", "specifier": "total=1.5", "outcomes": [
        {"id": "12", "desc": "Over 1.5", "odds": "1.22"},
        {"id": "13", "desc": "Under 1.5", "odds": "4.60"},
    ]}])
    parsed = sb._parse_event(ev)
    expected = (1 / 1.22 + 1 / 4.60) - 1
    assert parsed["margins"]["over_1_5"] == pytest.approx(expected, abs=1e-5)
    assert parsed["prices"]["over_1_5"] == 1.22


def test_double_chance_margin_is_scaled_by_coverage():
    """Three selections each covering two of three results sum to 2.0, not 1.0.

    Without the divisor double chance would report about 105% margin and the
    selector would treat the cheapest market on the board as the dearest.
    """
    ev = _event([{"id": "10", "specifier": "", "outcomes": [
        {"id": "9", "desc": "Home or Draw", "odds": "1.88"},
        {"id": "10", "desc": "Home or Away", "odds": "1.28"},
        {"id": "11", "desc": "Draw or Away", "odds": "1.26"},
    ]}])
    parsed = sb._parse_event(ev)
    expected = (1 / 1.88 + 1 / 1.28 + 1 / 1.26) / 2 - 1
    assert parsed["margins"]["home_or_draw"] == pytest.approx(expected, abs=1e-5)
    assert 0.0 < parsed["margins"]["home_or_draw"] < 0.20


def test_partial_market_yields_price_but_no_margin():
    """One side suspended is not a cheap market, and must not read as one."""
    ev = _event([{"id": "1", "specifier": "", "outcomes": [
        {"id": "1", "desc": "Home", "odds": "2.10"},
        {"id": "2", "desc": "Draw", "odds": "3.40"},
        # away price missing
    ]}])
    parsed = sb._parse_event(ev)
    assert parsed["prices"]["home_win"] == 2.10
    assert "home_win" not in parsed["margins"]


def test_event_without_prices_is_retained_for_market_diagnostics():
    assert sb._parse_event(_event([]))["prices"] == {}
    assert sb._parse_event({"homeTeamName": "", "awayTeamName": "X"}) is None


# ── Lookup ─────────────────────────────────────────────────

def _board():
    board = {}
    for home, away, ms in [
        ("Arsenal", "Chelsea", 1787598000000),
        ("Arsenal Sarandi", "Boca Juniors", 1787858000000),
        ("Hamburger SV", "Verl", 1787598000000),
    ]:
        board[f"{sb._norm(home)}|{sb._norm(away)}"] = {
            "event_id": f"sr:match:{home}", "home_team": home, "away_team": away,
            "home_squad": sb._squad(home), "away_squad": sb._squad(away),
            "kickoff_ms": ms, "prices": {"over_1_5": 1.20}, "margins": {"over_1_5": 0.04},
        }
    return board


def test_lookup_exact_and_fuzzy():
    board = _board()
    kickoff = "2026-08-24T19:00:00Z"
    assert sb.lookup(board, "Arsenal", "Chelsea", kickoff)["event_id"] == "sr:match:Arsenal"
    # ESPN spells it "Hamburg SV"; the board says "Hamburger SV".
    assert sb.lookup(board, "Hamburg SV", "SC Verl 1924", kickoff) is not None


def test_exact_key_wins_over_fuzzy_candidates():
    """A name that resolves exactly is never put to the ambiguity scan."""
    board = _board()
    # "Chelsea FC" normalises to "chelsea", so this is the exact key.
    assert sb.lookup(board, "Arsenal", "Chelsea FC", "2026-08-24T19:00:00Z")["event_id"] == "sr:match:Arsenal"


def test_lookup_rejects_ambiguity_rather_than_guessing():
    """Two plausible fixtures means no price, not a coin flip.

    The real shape of this: both clubs called Arsenal, both opponents called
    Chelsea, and a query carrying neither city. Without the ambiguity guard
    the first one iterated would win and the card would show a price from the
    wrong continent.
    """
    def entry(h, a, ms):
        return {"event_id": f"sr:{h}", "home_team": h, "away_team": a,
                "home_squad": "", "away_squad": "", "kickoff_ms": ms,
                "prices": {"over_1_5": 1.2}, "margins": {"over_1_5": 0.04}}

    board = {
        "arsenal london|chelsea london": entry("Arsenal London", "Chelsea London",
                                               1787598000000),
        "arsenal sarandi|chelsea buenos": entry("Arsenal Sarandi", "Chelsea Buenos",
                                                1787598000000),
    }
    assert sb.lookup(board, "Arsenal", "Chelsea", "") is None

    # With a kickoff far from the second fixture, only one candidate survives
    # and the lookup can safely resolve it.
    board["arsenal sarandi|chelsea buenos"]["kickoff_ms"] = 1787858000000
    hit = sb.lookup(board, "Arsenal", "Chelsea", "2026-08-24T19:00:00Z")
    assert hit is not None and hit["event_id"] == "sr:Arsenal London"


def test_lookup_empty_board():
    assert sb.lookup({}, "Arsenal", "Chelsea") is None


def test_apply_to_fixtures_leaves_model_inputs_alone():
    """Prices and margins move; `implied` must not.

    `predictor.py` reads `implied` to decide `has_market`, so writing a second
    book's probabilities there would change every prediction on the board and
    invalidate the calibration fit. Pricing is a display and selection concern.
    """
    board = _board()
    original_implied = {"home_win": 0.5, "away_win": 0.3, "draw": 0.2}
    fx = [{
        "home": {"name": "Arsenal"}, "away": {"name": "Chelsea"},
        "commence_time": "2026-08-24T19:00:00Z",
        "odds": {"implied": dict(original_implied), "provider": "DraftKings"},
    }]
    matched = sb.apply_to_fixtures(fx, board)
    assert matched == 1
    assert fx[0]["odds"]["implied"] == original_implied
    assert fx[0]["odds"]["provider"] == "SportyBet"
    assert fx[0]["odds"]["over_1_5"] == 1.20
    assert fx[0]["odds"]["margins"]["over_1_5"] == 0.04


def test_apply_to_fixtures_survives_malformed_input():
    board = _board()
    fx = [{"home": {"name": "Arsenal"}}, {}, {"home": None, "away": None}]
    assert sb.apply_to_fixtures(fx, board) == 0


def test_apply_to_fixtures_without_a_board_is_a_no_op():
    fx = [{"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}, "odds": {}}]
    assert sb.apply_to_fixtures(fx, {}) == 0
    assert fx[0]["odds"] == {}


# ── Aliases ────────────────────────────────────────────────

def test_aliases_resolve_clubs_the_feeds_name_differently():
    """No shared substring, so normalisation alone cannot join these."""
    assert sb._norm("Athletico-PR") == sb._norm("Paranaense")
    assert sb._norm("Wolverhampton Wanderers") == sb._norm("Wolves")
    assert sb._norm("CRB") == sb._norm("CR Brasil")


def test_aliases_do_not_collapse_distinct_clubs():
    """The risk an alias table carries: joining two teams that differ."""
    assert sb._norm("Atletico Mineiro") != sb._norm("America Mineiro")
    assert sb._norm("Manchester United") != sb._norm("Manchester City")
    assert sb._norm("Internacional") != sb._norm("Inter Milan")


def test_alias_keys_are_stored_normalised():
    """An alias written in raw form would never be looked up.

    Keys are consulted after normalisation, so any key that is not already in
    normalised form is dead weight that silently does nothing.
    """
    for key in sb._ALIASES:
        assert key == " ".join(key.split()), key
        assert key == key.lower(), key


# ── Complete catalogue and structured availability ─────────

def _page_event(index, home="Home FC", away="Away FC"):
    return {"eventId": f"e{index}", "homeTeamName": home,
            "awayTeamName": away, "estimateStartTime": 1787598000000,
            "markets": [{"id": "18", "specifier": "total=1.5", "outcomes": [
                {"id": "12", "desc": "Over", "odds": "1.22", "isActive": True},
                {"id": "13", "desc": "Under", "odds": "4.60", "isActive": True},
            ]}]}


def test_pagination_continues_until_declared_total(monkeypatch):
    calls = []
    def get(url):
        page = int(url.split("pageNum=")[1])
        calls.append(page)
        count = 100 if page < 3 else 1
        events = [_page_event((page - 1) * 100 + i,
                              f"Home {page}-{i}", f"Away {page}-{i}")
                  for i in range(count)]
        return {"data": {"totalNum": 201,
                         "tournaments": [{"name": "League", "events": events}]}}
    monkeypatch.setattr(sb, "_get_json", get)
    monkeypatch.setattr(sb, "_db_get", lambda key: None)
    monkeypatch.setattr(sb, "_db_set", lambda key, value: None)
    board = sb.fetch_board(force=True)
    assert calls == [1, 2, 3]
    assert sb.board_metadata(board)["is_complete"] is True
    assert sb.board_metadata(board)["fetched_total"] == 201


def test_incomplete_catalogue_does_not_claim_genuine_absence(monkeypatch):
    monkeypatch.setattr(sb, "_db_get", lambda key: None)
    monkeypatch.setattr(sb, "_db_set", lambda key, value: None)
    monkeypatch.setattr(sb, "_get_json", lambda url: {
        "data": {"totalNum": 300, "tournaments": [{
            "name": "League", "events": [_page_event(int(url.split("pageNum=")[1]))]
        }]}})
    board = sb.fetch_board(max_pages=2, force=True)
    assert sb.board_metadata(board)["is_complete"] is False
    result = sb.match_fixture(board, "Missing", "Fixture",
                              "2026-08-24T19:00:00Z")
    assert result["status"] == "SPORTYBET_DATA_ERROR"


def test_same_team_pair_on_multiple_dates_is_not_overwritten(monkeypatch):
    events = [_page_event(1), _page_event(2)]
    events[1]["estimateStartTime"] += 86400000
    monkeypatch.setattr(sb, "_db_get", lambda key: None)
    monkeypatch.setattr(sb, "_db_set", lambda key, value: None)
    monkeypatch.setattr(sb, "_get_json", lambda url: {
        "data": {"totalNum": 2, "tournaments": [{"name": "League",
                                                   "events": events}]}})
    board = sb.fetch_board(force=True)
    assert len(board["home|away"]) == 2


def _availability_board(outcomes=None, include_market=True, complete=True):
    refs = ({"18|total=1.5": {"outcomes": outcomes if outcomes is not None else {
        "12": {"active": True, "odds": 1.22},
        "13": {"active": True, "odds": 4.6},
    }}} if include_market else {})
    return {"__meta__": {"is_complete": complete, "snapshot_id": "snap1"},
            "home|away": [{"event_id": "e1", "home_team": "Home FC",
                             "away_team": "Away FC", "home_squad": "",
                             "away_squad": "", "kickoff_ms": 1787598000000,
                             "competition": "Premier League", "prices": {},
                             "margins": {}, "market_refs": refs}]}


def test_exact_selection_availability_states():
    args = ("Home FC", "Away FC", "2026-08-24T19:00:00Z",
            "Premier League", "over_1_5")
    assert sb.availability_for(_availability_board(), *args)["status"] == "BOOKABLE"
    assert sb.availability_for(_availability_board(include_market=False), *args)["status"] == "MARKET_NOT_FOUND"
    assert sb.availability_for(_availability_board(outcomes={}), *args)["status"] == "SELECTION_NOT_FOUND"
    suspended = {"12": {"active": False, "odds": 1.22}}
    assert sb.availability_for(_availability_board(suspended), *args)["status"] == "SELECTION_NOT_FOUND"
    no_odds = {"12": {"active": True, "odds": None}}
    assert sb.availability_for(_availability_board(no_odds), *args)["status"] == "ODDS_UNAVAILABLE"


def test_kickoff_and_league_diagnostics_are_explicit():
    board = _availability_board()
    mismatch = sb.match_fixture(board, "Home FC", "Away FC",
                                "2026-08-24T22:00:00Z", "Premier League")
    assert mismatch["status"] == "KICKOFF_MISMATCH"
    league = sb.match_fixture(board, "Home FC", "Away FC",
                              "2026-08-24T19:00:00Z", "La Liga")
    assert league["status"] == "MATCHED"
    assert league["league_diagnostic"] == "LEAGUE_MISMATCH"
