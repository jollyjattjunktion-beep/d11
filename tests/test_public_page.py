from app.public_page import render_home, render_sitemap


TEMPLATE = """
<title>{{PAGE_TITLE}}</title>
<meta name="description" content="{{META_DESCRIPTION}}">
<link rel="canonical" href="{{CANONICAL_URL}}">
<script type="application/ld+json">{{JSON_LD}}</script>
<b>{{MATCH_COUNT}}</b><b>{{LIVE_COUNT}}</b><b>{{UPCOMING_COUNT}}</b>
<p>{{UPDATED_AT}}</p><div>{{MATCH_LIST}}</div>
"""


def sample_match():
    return {
        "id": "fixture-1",
        "name": "NZ vs IND - India tour",
        "format": "ODI",
        "start_time": "2026-11-07T02:00:00Z",
        "venue": "Hnry Stadium, Wellington",
        "team_a": "NZ",
        "team_b": "IND",
        "team_a_name": "New Zealand",
        "team_b_name": "India",
        "team_a_image": "https://example.com/nz.png",
        "team_b_image": "https://example.com/ind.png",
        "series": "India tour of New Zealand ODI",
        "status": "upcoming",
    }


def test_homepage_replaces_all_seo_and_match_placeholders():
    rendered = render_home(TEMPLATE, [sample_match()], "https://fantasy.example", None)
    assert "{{" not in rendered
    assert "Upcoming Cricket Matches" in rendered
    assert "https://fantasy.example/" in rendered
    assert "New Zealand" in rendered
    assert "India" in rendered
    assert "SportsEvent" in rendered
    assert "Hnry Stadium" in rendered
    assert 'href="/match/fixture-1"' in rendered


def test_homepage_handles_empty_feed():
    rendered = render_home(TEMPLATE, [], "https://fantasy.example", None)
    assert "No live or upcoming matches" in rendered
    assert "<b>0</b>" in rendered


def test_homepage_escapes_untrusted_team_names_and_image_urls():
    match = sample_match()
    match["team_a_name"] = '<script>alert("x")</script>'
    match["team_a_image"] = "javascript:alert(1)"
    rendered = render_home(TEMPLATE, [match], "https://fantasy.example", None)
    assert "<script>alert(" not in rendered
    assert "javascript:alert(1)" not in rendered
    assert "&lt;script&gt;" in rendered


def test_sitemap_contains_canonical_homepage_url():
    sitemap = render_sitemap("https://fantasy.example", [sample_match()])
    assert "<urlset" in sitemap
    assert "<loc>https://fantasy.example/</loc>" in sitemap
    assert "<loc>https://fantasy.example/match/fixture-1</loc>" in sitemap
