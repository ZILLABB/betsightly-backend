"""October 2026 provider-confirmed Dutch / French / English FT regression."""
from datetime import datetime, timezone
from leagues import results_checker
from leagues.editorial_settlement import grade_manual_slip
from leagues.live_scores import infer_published_competition_slugs

# label, kickoff day, saved home/away, ESPN home/away, FT, market, grade
ROWS = [["ned.2","2026-10-16","FC Den Bosch","TOP Oss","FC Den Bosch","TOP Oss",2,1,"over_1_5","won"],["ned.2","2026-10-16","FC Eindhoven","Vitesse Arnhem","FC Eindhoven","Vitesse",0,1,"over_1_5","lost"],["ned.2","2026-10-16","Helmond Sport","NAC Breda","Helmond Sport","NAC Breda",0,2,"away_or_draw","won"],["ned.2","2026-10-16","VVV Venlo","Jong AZ Alkmaar","VVV-Venlo","Jong AZ",4,4,"over_2_5","won"],["ned.2","2026-10-19","Jong Ajax Amsterdam","De Graafschap","Jong Ajax","De Graafschap",2,1,"over_1_5","won"],["ned.2","2026-10-19","Jong FC Utrecht","Roda JC Kerkrade","Jong FC Utrecht","Roda JC Kerkrade",1,2,"over_1_5","won"],["ned.2","2026-10-23","FC Den Bosch","MVV Maastricht","FC Den Bosch","MVV Maastricht",2,2,"over_2_5","won"],["ned.2","2026-10-23","Vitesse Arnhem","FC Emmen","Vitesse","FC Emmen",0,2,"over_2_5","lost"],["ned.2","2026-10-23","NAC Breda","Heracles Almelo","NAC Breda","Heracles Almelo",1,1,"over_2_5","lost"],["ned.2","2026-10-23","TOP Oss","Jong Ajax Amsterdam","TOP Oss","Jong Ajax",3,3,"over_2_5","won"],["ned.2","2026-10-23","FC Volendam","Jong FC Utrecht","FC Volendam","Jong FC Utrecht",6,2,"over_2_5","won"],["ned.2","2026-10-23","Jong AZ Alkmaar","Helmond Sport","Jong AZ","Helmond Sport",5,4,"over_2_5","won"],["fra.2","2026-10-16","Reims","Dijon","Stade de Reims","Dijon FCO",4,2,"over_1_5","won"],["fra.2","2026-10-16","Stade Lavallois MFC","Clermont Foot","Stade Laval","Clermont Foot",3,3,"over_1_5","won"],["fra.2","2026-10-16","EA Guingamp","Pau FC","Guingamp","Pau",1,2,"over_1_5","won"],["fra.2","2026-10-23","Nancy-Lorraine","Stade Lavallois MFC","AS Nancy Lorraine","Stade Laval",1,0,"over_1_5","lost"],["eng.2","2026-10-14","Norwich","Southampton","Norwich City","Southampton",0,1,"btts_yes","lost"],["eng.2","2026-10-14","Lincoln City","West Ham","Lincoln City","West Ham United",0,6,"away_or_draw","won"],["eng.2","2026-10-17","Norwich","Portsmouth FC","Norwich City","Portsmouth",0,1,"over_1_5","lost"],["eng.2","2026-10-17","Swansea City","West Ham","Swansea City","West Ham United",0,1,"over_1_5","lost"]]


def test_eerste_divisie_country_registry_maps_to_verified_espn_slug():
    mapped, unknown = infer_published_competition_slugs([
        {"league": "Eerste Divisie", "home_team": "VVV Venlo",
         "away_team": "Jong AZ Alkmaar", "editorial_manual": True}])
    assert mapped == {"ned.2"} and unknown == 0


def test_all_twenty_saved_fixtures_match_only_same_orientation_and_day():
    observed = [
        {"home": provider_home, "away": provider_away, "date": day,
         "home_score": home_score, "away_score": away_score,
         "provider": "espn", "provider_event_id": str(i + 50000),
         "score_90": {"home": home_score, "away": away_score},
         "match_status": "FT", "completed": True}
        for i, (league, day, home, away, provider_home, provider_away,
                home_score, away_score, market, outcome) in enumerate(ROWS)
    ]
    indexed = results_checker._index_free_finals(observed)
    assert len(ROWS) == 20
    for league, day, home, away, _, _, h, a, market, outcome in ROWS:
        result = results_checker._lookup_settlement_score(indexed, home, away, day)
        assert result and (result["home_score"], result["away_score"]) == (h, a)
        assert results_checker._lookup_settlement_score(
            indexed, home, away, "2026-10-10") is None
        assert results_checker._lookup_settlement_score(
            indexed, away, home, day) is None
        record = {"games": [
            {"home_team": home, "away_team": away, "market": market,
             "kickoff": day + "T18:00:00Z", "status": "pending"},
        ], "booking": {"share_code": "UNCHANGED"}}
        settled = grade_manual_slip(
            record, indexed,
            now=datetime(2026, 10, 28, 10, tzinfo=timezone.utc))
        assert settled["result_status"] == outcome
        assert settled["booking"] == record["booking"]
        assert settled["games"][0]["settlement_evidence"]["provider"] == "espn"
