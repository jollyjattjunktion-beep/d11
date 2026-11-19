from app.main import _tg_player_list


def test_tg_player_list_accepts_flat_player_list():
    rows = [{"playerId": 1, "name": "Player One"}]
    assert _tg_player_list(rows) == rows


def test_tg_player_list_flattens_category_groups():
    rows = _tg_player_list({
        "Playing XI": [{"id": 1, "playerName": "Player One"}],
        "Bench": [{"id": 2, "playerName": "Player Two"}],
    })
    assert len(rows) == 2
    assert rows[0]["_lineup_category"] == "Playing XI"
    assert rows[1]["_lineup_category"] == "Bench"


def test_tg_player_list_handles_nested_category_groups():
    rows = _tg_player_list({
        "team1": {"Playing XI": [{"id": "1", "name": "A"}]},
        "team2": {"Bench": [{"id": "2", "name": "B"}]},
    })
    assert len(rows) == 2
    assert rows[0]["id"] == "1"
    assert rows[1]["_lineup_category"] == "Bench"


def test_tg_player_list_returns_empty_for_unrecognized_shape():
    assert _tg_player_list(None) == []
    assert _tg_player_list("not-a-list") == []
