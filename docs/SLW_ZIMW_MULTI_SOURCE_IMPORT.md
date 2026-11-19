# SL-W vs ZIM-W — Multi-source D11 match import

## Source ownership

- AI11 analysis URL: batting/bowling/series profiles, selection %, captain/vice-captain trends and available match context.
- TeamGeneration match ID: official squad/playing status, batting/bowling roles, credits and player IDs.
- Cricbuzz venue URL: canonical stadium identity and format-specific historical ground statistics.

All three imports are linked to one D11 match keyed by the TeamGeneration match ID. AI11 must pass the existing same-fixture/team/format/date checks. TeamGeneration remains authoritative for credits and official playing-XI status. Cricbuzz remains authoritative for the ground ID and venue history.

## Example request

POST /api/v1/admin/import/multi-source-match

Header: X-Admin-Token: <configured admin token>

```json
{
  "ai11_analysis_url": "https://www.ai11.in/cricket/series/icc-women-s-emerging-nations-trophy-2026-27/match/sri-lanka-women-vs-zimbabwe-women-2nd-match-super-six-2026",
  "teamgeneration_match_id": "m11c_120555",
  "teamgeneration_url": "https://teamgeneration.in/match/m11c_120555",
  "cricbuzz_venue_url": "https://www.cricbuzz.com/cricket-series/13420/icc-womens-emerging-nations-trophy-2026/venues/1438500/seven-districts-ground"
}
```

## Expected source mapping

- AI11: ICC Women's Emerging Nations Trophy 2026-27, Sri Lanka Women vs Zimbabwe Women, Super Six, T20.
- TeamGeneration: match ID m11c_120555; import its player list, roles, credits, playing flags and lineup status. A lineup not announced by the provider must remain provisional; do not invent an official XI.
- Cricbuzz: series ID 13420, venue ID 1438500, Seven Districts Ground, Ajman, UAE.

The Cricbuzz venue page exposes a T20 sample of 10 matches: batting-first wins 4, bowling-first wins 6, average first innings 126, average second innings 109. Preserve the 10-match sample size and low confidence. Do not infer pace/spin assistance when the source does not publish it.

AI11 calls this ground 'Seven Districts Sports Club'; store that display name as an alias of the Cricbuzz canonical 'Seven Districts Ground' record to avoid duplicate stadiums.

## Re-import behaviour

The combined endpoint reuses the TeamGeneration match identity and existing importers. Re-run it after TeamGeneration updates the lineup to refresh official playing flags. The importer must preserve manual verified credits and avoid creating a separate AI11-only match when a target match is supplied.