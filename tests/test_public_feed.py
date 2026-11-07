from datetime import datetime, timedelta, timezone

from app.public_feed import (
    classify_fixture_status,
    normalize_fixture,
    normalize_match_format,
    parse_source_datetime,
    manual_venue_is_locked,
    should_update_venue_from_feed,
)


NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def test_normalize_fixture_creates_a_scheduled_odi_record():
    record = normalize_fixture({
        "id": 123,
        "series": "India tour of New Zealand ODI",
        "startTime": "2026-11-07T02:00:00Z",
        "status": "upcoming",
        "left": {"code": "NZ", "name": "New Zealand", "image": "https://img.example/nz.png"},
        "right": {"code": "IND", "name": "India", "image": "https://img.example/ind.png"},
    }, now=NOW)
    assert record["id"] == "123"
    assert record["format"] == "ODI"
    assert record["team_a"] == "NZ"
    assert record["team_b"] == "IND"
    assert record["status"] == "upcoming"
    assert record["visible"] is True
    assert record["team_a_image"].startswith("https://")


def test_explicit_completed_fixture_is_hidden():
    assert classify_fixture_status(
        "completed", "2026-11-06T10:00:00Z", "T20", now=NOW
    ) == "completed"


def test_live_fixture_remains_visible():
    assert classify_fixture_status(
        "in_progress", "2026-11-06T10:00:00Z", "T20", now=NOW
    ) == "live"


def test_stale_t20_fixture_without_status_is_expired():
    start = (NOW - timedelta(hours=8)).isoformat()
    assert classify_fixture_status("", start, "T20", now=NOW) == "completed"


def test_recently_started_t20_without_status_is_treated_as_live():
    start = (NOW - timedelta(hours=2)).isoformat()
    assert classify_fixture_status("", start, "T20", now=NOW) == "live"


def test_test_match_has_a_longer_expiry_window_than_t20():
    start = (NOW - timedelta(days=4)).isoformat()
    assert classify_fixture_status("", start, "TEST", now=NOW) == "live"


def test_cancelled_fixture_is_hidden():
    assert classify_fixture_status(
        "cancelled", "2026-11-07T02:00:00Z", "ODI", now=NOW
    ) == "cancelled"


def test_format_detection_supports_womens_and_domestic_names():
    assert normalize_match_format("Women's Big Bash League T20") == "T20"
    assert normalize_match_format("Women's ODI series") == "ODI"
    assert normalize_match_format("New Zealand Test tour") == "TEST"


def test_epoch_milliseconds_are_normalized_to_utc():
    parsed = parse_source_datetime(1794016800000)
    assert parsed is not None
    assert parsed.tzinfo == timezone.utc



def test_manual_venue_override_survives_non_empty_provider_venue():
    intelligence = {"manual_venue_override": True}
    assert manual_venue_is_locked(intelligence, "My selected ground")
    assert not should_update_venue_from_feed(
        "My selected ground", "Different provider ground", intelligence
    )


def test_legacy_admin_saved_venue_is_protected_after_upgrade():
    # Older releases did not write manual_venue_override, but they did record
    # admin_match_updated_at whenever an administrator saved a match.
    intelligence = {"admin_match_updated_at": "2026-11-07T10:00:00+00:00"}
    assert manual_venue_is_locked(intelligence, "Admin-selected stadium")
    assert not should_update_venue_from_feed(
        "Admin-selected stadium", "Provider stadium", intelligence
    )


def test_unlocked_venue_follows_provider_feed():
    assert not manual_venue_is_locked({"public_feed": {}}, None)
    assert should_update_venue_from_feed(None, "Provider stadium", {"public_feed": {}})


def test_missing_provider_venue_does_not_erase_existing_venue():
    assert not should_update_venue_from_feed("Known ground", None, {})
    assert not should_update_venue_from_feed("Known ground", "", {})


def test_manually_cleared_venue_stays_locked_until_explicit_feed_reset():
    intelligence = {"manual_venue_override": True}
    assert manual_venue_is_locked(intelligence, None)
    assert not should_update_venue_from_feed(None, "Provider ground", intelligence)
