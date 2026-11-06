from app.match_page import render_match_detail


TEMPLATE = """
<title>{{PAGE_TITLE}}</title>
<meta name="description" content="{{META_DESCRIPTION}}">
<link rel="canonical" href="{{CANONICAL_URL}}">
<script type="application/ld+json">{{JSON_LD}}</script>
<h1>{{MATCH_TITLE}}</h1><p>{{SERIES}} {{FORMAT}} {{STATUS_LABEL}} {{KICKOFF}} {{VENUE}} {{MATCH_ID}}</p>
<div>{{TEAM_A_LOGO}} {{TEAM_A}} {{TEAM_A_FULL}} {{TEAM_B_LOGO}} {{TEAM_B}} {{TEAM_B_FULL}}</div>
<p>{{UPDATED}} {{PLAYER_COUNT}} {{XI_STATUS}} {{CREDIT_COUNT}}</p>
<div>{{IMPORT_NOTICE_CLASS}} {{IMPORT_NOTICE}}</div>
<div>{{SQUAD_CONTENT}}</div><div>{{SCORECARD_CONTENT}}</div>
<div>{{PITCH}} {{TOSS}} {{DATA_NOTE}}</div>
"""


def test_match_page_renders_imported_squad_and_match_url():
    match = {
        "id": "113980", "name": "NZ vs IND ODI", "format": "ODI",
        "start_time": "2026-11-07T02:00:00Z", "venue": "Hnry Stadium",
        "team_a": "NZ", "team_b": "IND", "team_a_name": "New Zealand",
        "team_b_name": "India", "series": "India tour of New Zealand",
        "status": "upcoming",
    }
    players = [{
        "player_id": "TG-1", "player_name": "Virat Kohli", "team": "IND",
        "role": "BAT", "credits": 9.0, "selection_pct": 85.0,
        "status": "not_announced", "image": "https://example.com/player.png",
        "captain_pct": 29.9, "vice_captain_pct": 11.6,
    }]
    rendered = render_match_detail(
        TEMPLATE, match,
        {"public_feed": {"team_a_image": "https://example.com/nz.png"}},
        players, [], "https://fantasy.example",
        "1 player imported from source.", True,
    )
    assert "{{" not in rendered
    assert "Virat Kohli" in rendered
    assert "85.0% selected" in rendered
    assert "Hnry Stadium" in rendered
    assert "https://fantasy.example/match/113980" in rendered
    assert "Players imported" not in rendered


def test_match_page_handles_empty_squad_and_scorecard():
    match = {
        "id": "match-2", "name": "A vs B", "format": "T20",
        "team_a": "A", "team_b": "B", "status": "upcoming",
    }
    rendered = render_match_detail(
        TEMPLATE, match, {}, [], [], "https://fantasy.example",
        "Squad not yet available.", False,
    )
    assert "Squad has not been imported" in rendered
    assert "No match-specific scorecard records" in rendered
    assert "Squad not yet available." in rendered
