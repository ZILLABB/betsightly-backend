import os
from pathlib import Path


def test_runtime_cache_paths_are_outside_tracked_repository_data():
    from leagues import base_rates, calibrator, elo_engine, espn_source
    from leagues import odds_shop, team_history

    root = Path(os.environ["BETSIGHTLY_CACHE_ROOT"]).resolve()
    paths = [
        base_rates.CACHE_PATH, calibrator.CACHE_PATH, elo_engine.CACHE_PATH,
        espn_source.CACHE_PATH, odds_shop.CACHE_PATH, odds_shop.BUDGET_PATH,
        team_history.CACHE_PATH,
    ]
    assert all(path.resolve().parent == root for path in paths)
    assert all("leagues/data" not in path.as_posix() for path in paths)
