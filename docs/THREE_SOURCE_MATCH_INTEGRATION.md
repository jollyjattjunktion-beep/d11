# Three-source match integration: Sri Lanka Women vs Zimbabwe Women

## Source ownership

Use one canonical D11 match ID: the Team Generation fixture ID `m11c_120555`.

| Purpose | Authoritative source | Source URL / ID |
|---|---|---|
| Player analysis, recent/form and fantasy profile signals | AI11 | `https://www.ai11.in/cricket/series/icc-women-s-emerging-nations-trophy-2026-27/match/sri-lanka-women-vs-zimbabwe-women-2nd-match-super-six-2026` |
| Squad, player IDs, credits and Playing XI status | Team Generation | `m11c_120555` |
| Stadium identity and historical pitch data | Cricbuzz | `https://www.cricbuzz.com/cricket-series/13420/icc-womens-emerging-nations-trophy-2026/venues/1438500/seven-districts-ground` |

## One-shot integration endpoint

After this branch is merged and deployed, call:

`POST /api/v1/admin/matches/integrate-sources`

The request body is preconfigured with the three source references above. In Swagger, authorize with the existing admin token and execute the endpoint with the default request body. You may also submit an explicit JSON body:

```json
{
  "ai11_analysis_url": "https://www.ai11.in/cricket/series/icc-women-s-emerging-nations-trophy-2026-27/match/sri-lanka-women-vs-zimbabwe-women-2nd-match-super-six-2026",
  "teamgeneration_match_id": "m11c_120555",
  "cricbuzz_venue_url": "https://www.cricbuzz.com/cricket-series/13420/icc-womens-emerging-nations-trophy-2026/venues/1438500/seven-districts-ground",
  "import_ai11": true,
  "import_teamgeneration": true,
  "import_cricbuzz_venue": true
}
```

To have the endpoint discover the Cricbuzz venue from the Cricbuzz schedule and match page instead of using the explicit venue URL, set `cricbuzz_venue_url` to `null`. Discovery is accepted only when one unique fixture matches the two Team Generation teams; otherwise it returns a clear 422 response and does not guess.

## Storage and merge rules

- Team Generation is imported first and owns the D11 match/squad IDs, credits and lineup state.
- AI11 is linked to that existing D11 match using the repository's safe player-name mapper. It must not create a second AI11-only match for this workflow.
- Cricbuzz venue URL identity is parsed and verified against the venue page's provider venue ID before saving.
- Venue profile, format statistics, canonical source URL, series ID and venue ID are written to the existing `venues` catalogue and `match_intelligence` row.
- Existing Team Generation XI data, AI11 profiles and manual match intelligence are retained as separate source fields; a provider's data should not silently replace another provider's data.
- Match format is derived from Team Generation; T10 is explicitly recognized. AI11 analysis format must match the target D11 match.
- The Cricbuzz stats parser only claims formats actually shown on the stadium page. It does not invent pace/spin data.

## Venue reference for this fixture

Cricbuzz's Seven Districts Ground page is venue ID `1438500`, series ID `13420`. Its current T20 summary shows 10 matches, 4 batting-first wins, 6 bowling-first wins, average first innings 126 and average second innings 109. These values are read from the page on import, not hard-coded into the engine.

## Validation and operational notes

Tests cover the URL identity, schedule live-score links, venue-anchor extraction, women-team slug aliases, T20 venue-stat parsing and the request defaults. Run the repository's full test suite and verify the live importer response before considering the integration production-ready.

No changes to production data or Render deployment are performed by this branch itself.
