"""Final Builder V2 product contract for this staging release."""

from leagues import builder_v2


def test_final_builder_product_contract_is_frozen():
    assert builder_v2.MAX_GAME_COUNT == 50
    assert builder_v2.V2_HORIZONS == {"today", "3_days", "7_days"}
    assert builder_v2.V2_MODES == {
        "target_odds",
        "game_count",
        "strongest",
        "manual",
    }


def test_final_builder_never_raises_game_cap_silently():
    assert builder_v2.MAX_GAME_COUNT <= 50
