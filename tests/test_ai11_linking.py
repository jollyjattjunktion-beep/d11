from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import Match, MatchIntelligence, MatchSquad, Player, PlayerSourceProfile
from app.schemas import AI11ImportRequest, TeamRequest


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, factory()


def test_ai11_profiles_link_to_existing_tg_match_and_preserve_tg_data(monkeypatch):
    engine, db = make_db()
    try:
        db.add(Match(
            id="tg-match-1", name="MR vs AS WBBL", format="T20",
            venue="Existing saved ground", team_a="MR", team_b="AS",
            status="upcoming", source="TEAM_GENERATION",
        ))
        db.add(Player(id="tg-wareham", name="Georgia Wareham"))
        db.add(Player(id="tg-matthews", name="Hayley Matthews"))
        db.add(MatchSquad(
            match_id="tg-match-1", player_id="tg-wareham", team="MR",
            role="AR", credits=9.5, selection_pct=85.0,
            status="confirmed", source="TEAM_GENERATION",
        ))
        db.add(MatchSquad(
            match_id="tg-match-1", player_id="tg-matthews", team="MR",
            role="AR", credits=9.0, selection_pct=90.0,
            status="playing", source="TEAM_GENERATION",
        ))
        db.add(MatchIntelligence(
            match_id="tg-match-1",
            data={"venue_id": "CRICBUZZ:77", "auto_venue_analysis": {"pitch_type": "pace"}},
        ))
        db.commit()

        parsed = {
            "match_id": "ai11-source-match",
            "title": "Melbourne Renegades Women vs Adelaide Strikers Women",
            "format": "T20",
            "team_a": "Melbourne Renegades Women",
            "team_b": "Adelaide Strikers Women",
            "venue": "Some Ground",
            "players": [
                {"id": "g-wareham", "name": "G Wareham", "team": "MR",
                 "role": "AR", "selection_pct": 88.0, "status": "unknown"},
                {"id": "h-matthews", "name": "H Matthews", "team": "MR",
                 "role": "AR", "selection_pct": 91.0, "status": "unknown"},
                {"id": "unknown-player", "name": "Unknown Player", "team": "AS",
                 "role": "BAT", "selection_pct": 12.0, "status": "unknown"},
            ],
            "profiles": [
                {"player_id": "g-wareham", "player_name": "G Wareham", "team": "MR",
                 "role": "AR", "ai11_statistics": {"matches": 30, "batting_innings": 24,
                 "batting_average": 34.0, "bowling_innings": 22, "wickets": 24},
                 "ai11_series_summary": {"series_matches": 3, "series_average_points": 92}},
                {"player_id": "h-matthews", "player_name": "H Matthews", "team": "MR",
                 "role": "AR", "ai11_statistics": {"matches": 28, "batting_innings": 25,
                 "batting_average": 38.0, "bowling_innings": 19, "wickets": 17},
                 "ai11_series_summary": {"series_matches": 3, "series_average_points": 88}},
            ],
            "intelligence": {
                "pitch_type": "pace",
                "pitch_notes": "Surface favours seam bowling",
                "pitch_recommendation": "Pace-friendly",
                "average_first_innings": 165,
                "average_second_innings": 148,
                "venue_matches": 12,
                "toss_completed": True,
                "toss_winner": "Melbourne Renegades Women",
                "toss_decision": "bat",
                "batting_first_team": "Melbourne Renegades Women",
                "chasing_team": "Adelaide Strikers Women",
            },
        }
        monkeypatch.setattr(main, "fetch_page", lambda _url: "<html></html>")
        monkeypatch.setattr(main, "parse_analysis", lambda _html: parsed)
        monkeypatch.setattr(main, "parse_fantasy", lambda _html: {
            "credits": {}, "credits_found": 0,
            "dynamic_content_may_require_browser": True,
        })

        result = main.import_ai11(
            AI11ImportRequest(
                analysis_url="https://www.ai11.in/cricket/series/example/match/example",
                target_match_id="tg-match-1",
            ),
            _admin=True,
            db=db,
        )

        assert result["linked_to_existing_match"] is True
        assert result["match_id"] == "tg-match-1"
        assert result["players_matched"] == 2
        assert result["players_unmatched"] == ["Unknown Player"]

        wareham_profile = db.get(PlayerSourceProfile, ("tg-match-1", "tg-wareham", "AI11"))
        assert wareham_profile is not None
        assert wareham_profile.data["ai11_statistics"]["wickets"] == 24
        assert wareham_profile.data["player_id"] == "tg-wareham"
        assert wareham_profile.data["team"] == "MR"

        wareham = db.get(MatchSquad, ("tg-match-1", "tg-wareham"))
        matthews = db.get(MatchSquad, ("tg-match-1", "tg-matthews"))
        assert wareham.credits == 9.5
        assert wareham.status == "confirmed"
        assert wareham.selection_pct == 85.0
        assert matthews.status == "playing"

        saved_match = db.get(Match, "tg-match-1")
        assert saved_match.name == "MR vs AS WBBL"
        assert saved_match.team_a == "MR"
        assert saved_match.team_b == "AS"
        assert saved_match.venue == "Existing saved ground"

        intelligence = db.get(MatchIntelligence, "tg-match-1").data
        assert intelligence["venue_id"] == "CRICBUZZ:77"
        assert intelligence["pitch_type"] == "pace"
        assert intelligence["average_first_innings"] == 165
        assert intelligence["toss_winner"] == "MR"
        assert intelligence["batting_first_team"] == "MR"
        assert intelligence["chasing_team"] == "AS"
        assert result["credits_ready_for_team_builder"] is True
    finally:
        db.close()
        engine.dispose()


def test_both_innings_without_toss_builds_both_possible_batting_orders(monkeypatch):
    engine, db = make_db()
    try:
        db.add(Match(
            id="no-toss-match", name="MR vs AS", format="T20",
            team_a="MR", team_b="AS", status="upcoming",
        ))
        roles = ["WK", "BAT", "BAT", "BAT", "AR", "AR",
                 "BOWL", "BOWL", "BOWL", "BOWL", "BOWL", "BOWL"]
        predictions = []
        for index, role in enumerate(roles):
            player_id = f"p{index}"
            team = "MR" if index < 6 else "AS"
            db.add(Player(id=player_id, name=f"Player {index}"))
            db.add(MatchSquad(
                match_id="no-toss-match", player_id=player_id, team=team,
                role=role, credits=8.0, selection_pct=50,
                status="confirmed", source="TEAM_GENERATION",
            ))
            predictions.append({
                "player_id": player_id, "player_name": f"Player {index}",
                "team": team, "role": role, "credits": 8.0,
                "selection_pct": 50, "status": "confirmed",
                "expected_points": None, "floor_points": None,
                "ceiling_points": None, "consistency": 0,
                "upside": 0, "risk": "unknown", "condition_factor": 1.0,
            })
        db.commit()
        monkeypatch.setattr(main, "predict_match", lambda _db, _match_id: predictions)

        result = main.generate_teams(
            "no-toss-match",
            TeamRequest(
                strategies=["balanced"], teams_per_strategy=1,
                generation_mode="provisional", score_mode="both",
            ),
            db,
        )
        teams = result["teams"]["provisional"]["balanced"]
        assert len(teams) == 4
        labels = {team["scenario_label"] for team in teams}
        assert labels == {
            "Batting first • MR", "Chasing second • AS",
            "Batting first • AS", "Chasing second • MR",
        }
        assert result["score_scenario"]["mode"] == "both"
    finally:
        db.close()
        engine.dispose()
