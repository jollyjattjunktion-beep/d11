import pytest

from app.importers.teamgeneration_lineup import (
    parse_teamgeneration_lineup,
    validate_teamgeneration_match_url,
)


def make_payload(status="announced", playing_a=11, playing_b=11):
    players = []
    for team, count in ((0, playing_a), (1, playing_b)):
        for index in range(11):
            players.append({
                "playerId": f"{team}-{index}",
                "name": f"Player {team} {index}",
                "team": team,
                "role": index % 4,
                "playing": 1 if index < count else 0,
                "lineupOrder": index + 1,
            })
    return {
        "match": {
            "id": "m11c_120555",
            "series": "ICC Women's Emerging Nations Trophy",
            "startTime": "2026-11-20T05:00:00Z",
            "left": {"code": "SLW", "name": "Sri Lanka Women"},
            "right": {"code": "ZIMW", "name": "Zimbabwe Women"},
        },
        "detail": {
            "lineupStatus": status,
            "updatedAt": "2026-11-19T10:00:00Z",
            "players": players,
        },
    }


def test_validate_teamgeneration_match_url_extracts_id():
    assert validate_teamgeneration_match_url("https://teamgeneration.in/match/m11c_120555") == "m11c_120555"


@pytest.mark.parametrize("url", [
    "http://teamgeneration.in/match/m11c_120555",
    "https://evil.example/match/m11c_120555",
    "https://user:pass@teamgeneration.in/match/m11c_120555",
    "https://teamgeneration.in:8443/match/m11c_120555",
    "https://teamgeneration.in/match/m11c_120555?next=https://evil.example",
    "https://teamgeneration.in/matches/m11c_120555",
])
def test_validate_teamgeneration_match_url_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_teamgeneration_match_url(url)


def test_parse_teamgeneration_lineup_confirms_only_two_complete_xis():
    parsed = parse_teamgeneration_lineup(make_payload(), "m11c_120555")
    assert parsed["lineup_confirmed"] is True
    assert parsed["playing_counts"] == {"0": 11, "1": 11}
    assert len(parsed["players"]) == 22
    assert parsed["players"][0]["role"] == "WK"


def test_partial_or_unannounced_lineup_remains_provisional():
    partial = parse_teamgeneration_lineup(make_payload(playing_a=11, playing_b=10))
    assert partial["provider_xi_complete"] is False
    assert partial["lineup_confirmed"] is False

    pending = parse_teamgeneration_lineup(make_payload(status="not_announced"))
    assert pending["provider_xi_complete"] is True
    assert pending["lineup_confirmed"] is False


def test_parse_rejects_response_for_a_different_match():
    with pytest.raises(ValueError, match="different match ID"):
        parse_teamgeneration_lineup(make_payload(), "different_match")
