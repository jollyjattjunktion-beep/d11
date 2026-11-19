import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import Match, Player, MatchIntelligence, MatchSquad, PlayerSourceProfile
from app.schemas import TeamGenerationLineupImportRequest
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

def test_camel_case_not_announced_status_is_not_official():
    parsed = parse_teamgeneration_lineup(make_payload(status="notAnnounced"))
    assert parsed["provider_xi_complete"] is True
    assert parsed["lineup_confirmed"] is False


def make_test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_lineup_import_only_updates_xi_and_preserves_ai11_profiles_and_credits(monkeypatch):
    engine, db = make_test_db()
    try:
        db.add(Match(
            id="ai11-slw-zimw", name="Sri Lanka Women vs Zimbabwe Women",
            format="T20", team_a="Sri Lanka Women", team_b="Zimbabwe Women",
            status="upcoming", source="AI11",
        ))
        for team_index, team_name in ((0, "Sri Lanka Women"), (1, "Zimbabwe Women")):
            for index in range(11):
                player_id = f"ai11-{team_index}-{index}"
                player_name = f"Player {team_index} {index}"
                db.add(Player(id=player_id, name=player_name))
                db.add(MatchSquad(
                    match_id="ai11-slw-zimw", player_id=player_id, team=team_name,
                    role="BAT", credits=8.5, selection_pct=55.0,
                    status="unknown", source="AI11",
                ))
                if team_index == 0 and index == 0:
                    db.add(PlayerSourceProfile(
                        match_id="ai11-slw-zimw", player_id=player_id,
                        source="AI11", data={"ai11_statistics": {"runs": 321}},
                    ))
        db.commit()

        source_payload = make_payload()
        monkeypatch.setattr(main, "_teamgeneration_request", lambda _url: source_payload)
        result = main.import_teamgeneration_lineup(
            "ai11-slw-zimw",
            TeamGenerationLineupImportRequest(
                url="https://teamgeneration.in/match/m11c_120555"
            ),
            _admin=True,
            db=db,
        )

        assert result["mapped_lineup_confirmed"] is True
        assert result["players_matched"] == 22
        assert result["selected_by_team"] == {
            "Sri Lanka Women": 11,
            "Zimbabwe Women": 11,
        }
        squads = db.query(MatchSquad).filter_by(match_id="ai11-slw-zimw").all()
        assert len(squads) == 22
        assert all(row.credits == 8.5 for row in squads)
        assert all(row.source == "AI11" for row in squads)
        assert all(row.status == "playing" for row in squads)
        ai11_profile = db.get(PlayerSourceProfile, ("ai11-slw-zimw", "ai11-0-0", "AI11"))
        assert ai11_profile.data["ai11_statistics"]["runs"] == 321
        tg_profile = db.get(PlayerSourceProfile, ("ai11-slw-zimw", "ai11-0-0", "TEAM_GENERATION_LINEUP"))
        assert tg_profile.data["source_match_id"] == "m11c_120555"
        intelligence = db.get(MatchIntelligence, "ai11-slw-zimw")
        assert intelligence.data["teamgeneration_lineup_source_url"].endswith("/m11c_120555")
    finally:
        db.close()
        engine.dispose()


def test_partial_teamgeneration_xi_does_not_mark_unselected_players_unavailable(monkeypatch):
    engine, db = make_test_db()
    try:
        db.add(Match(
            id="ai11-partial", name="Sri Lanka Women vs Zimbabwe Women",
            format="T20", team_a="Sri Lanka Women", team_b="Zimbabwe Women",
            status="upcoming", source="AI11",
        ))
        for team_index, team_name in ((0, "Sri Lanka Women"), (1, "Zimbabwe Women")):
            for index in range(11):
                player_id = f"partial-{team_index}-{index}"
                db.add(Player(id=player_id, name=f"Player {team_index} {index}"))
                db.add(MatchSquad(
                    match_id="ai11-partial", player_id=player_id, team=team_name,
                    role="BAT", credits=8.5, selection_pct=50.0,
                    status="unknown", source="AI11",
                ))
        db.commit()

        monkeypatch.setattr(
            main, "_teamgeneration_request",
            lambda _url: make_payload(playing_a=11, playing_b=10),
        )
        result = main.import_teamgeneration_lineup(
            "ai11-partial",
            TeamGenerationLineupImportRequest(
                url="https://teamgeneration.in/match/m11c_120555"
            ),
            _admin=True,
            db=db,
        )

        assert result["mapped_lineup_confirmed"] is False
        assert result["lineup_confirmed"] is False
        assert db.get(MatchSquad, ("ai11-partial", "partial-1-10")).status == "unknown"
        assert db.get(MatchSquad, ("ai11-partial", "partial-1-9")).status == "probable"
    finally:
        db.close()
        engine.dispose()
