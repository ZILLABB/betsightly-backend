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
    ("Athletico-PR", "athletico pr"),
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
    assert sb._kickoff_ok(entry, "2026-08-24T22:00:00Z")     # same match, feeds disagree
    assert not sb._kickoff_ok(entry, "2026-08-27T15:00:00Z")  # different match


def test_kickoff_guard_abstains_without_data():
    """Missing timestamps cost coverage, never correctness."""
    assert sb._kickoff_ok({"kickoff_ms": None}, "2026-08-24T19:00:00Z")
    assert sb._kickoff_ok({"kickoff_ms": 1787598000000}, "")
    assert sb._kickoff_ok({"kickoff_ms": 1787598000000}, "not-a-date")


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


def test_event_without_usable_prices_is_dropped():
    assert sb._parse_event(_event([])) is None
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
    assert sb.lookup(board, "Arsenal", "Chelsea")["event_id"] == "sr:match:Arsenal"
    # ESPN spells it "Hamburg SV"; the board says "Hamburger SV".
    assert sb.lookup(board, "Hamburg SV", "SC Verl 1924") is not None


def test_exact_key_wins_over_fuzzy_candidates():
    """A name that resolves exactly is never put to the ambiguity scan."""
    board = _board()
    # "Chelsea FC" normalises to "chelsea", so this is the exact key.
    assert sb.lookup(board, "Arsenal", "Chelsea FC", "")["event_id"] == "sr:match:Arsenal"


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
