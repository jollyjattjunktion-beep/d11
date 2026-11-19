import pytest

from app.schemas import MatchSourceIntegrationRequest


def test_emerging_nations_source_integration_defaults():
    payload = MatchSourceIntegrationRequest()
    assert payload.ai11_analysis_url.endswith(
        "/sri-lanka-women-vs-zimbabwe-women-2nd-match-super-six-2026"
    )
    assert payload.teamgeneration_match_id == "m11c_120555"
    assert payload.cricbuzz_venue_url.endswith(
        "/venues/1438500/seven-districts-ground"
    )
    assert payload.import_ai11 is True
    assert payload.import_teamgeneration is True
    assert payload.import_cricbuzz_venue is True


def test_source_integration_allows_automatic_cricbuzz_venue_discovery():
    payload = MatchSourceIntegrationRequest(cricbuzz_venue_url=None)
    assert payload.cricbuzz_venue_url is None
