# TeamGeneration Research Overview integration

## Source payload received

Endpoint: `https://v2.tgsoftware-api.online/research/overview`

The supplied response contains aggregate research over 245 matches. It is not a player-by-player report and does not identify its competition, season, venue, format or gender in the JSON.

Observed values in the supplied sample:

- 245 total matches; 239 matches have a known winner and toss.
- Toss won match won: 123 / 239 (51.46%).
- Batting first won: 117 / 239 (48.95%).
- Toss decisions are reported as 66 bat and 179 bowl (245 total), while `tossKnown` is 239. This mismatch is preserved and flagged for review.
- First-innings average: 192.74 runs and 7.13 wickets.
- Second-innings average: 168.47 runs and 6.45 wickets.
- First-innings average exceeds second innings by 24.27 runs (12.59% of the first-innings average).
- Average pace wickets: 7.96; average spin wickets: 4.81. The source does not define the precise aggregation or denominator, so these are stored as reported rather than turned into venue-specific pitch ratings.
- Average Dream Team total: 1307.28 points.
- Captain from winning side: 74.48% (178); vice-captain from winning side: 65.69% (157).
- Average low-owned / high-owned players: 5.05 / 5.95.
- Ownership percentage-split frequencies include 5-6 (25.31%), 4-7 (22.45%), and 6-5 (20.82%).
- Team partition frequencies include 6:5 (33.47%), 7:4 (31.02%), and 5:6 (21.22%).
- Average Dream Team credits: 89.26, with P10 84.5 and P90 92.5. Treat these as provider-specific guidance, not a universal Dream11 credit rule.

## What this data can support

1. Portfolio-level ownership split guidance, especially for Grand League variants.
2. Historical team partition and player-group coverage diagnostics.
3. Captain/vice-captain research such as the reported share selected from the winning side.
4. Aggregate scoring and pace/spin wicket context when the sample scope is correctly identified.

## What it cannot support by itself

- Individual player expected runs, wickets or fantasy points.
- A player's expected batting position or expected overs.
- Powerplay or death-over bowling allocation.
- A player-vs-player matchup.
- A venue-specific pitch report unless the scope metadata says this is a venue sample.
- A format- or competition-specific conclusion unless the research scope is identified.

The array order of `avgPointsByRole`, `captainRolePct`, `captainRoleCount`, `vcRolePct`, `vcRoleCount` and the order in `combinationFreq` is not labelled in the supplied JSON. D11 preserves these as unmapped arrays/patterns and does not assume WK/BAT/AR/BOWL order.

## Import and persistence

- Admin page: `/admin/engine/`
- New action: `tg_research`
- Service: `app/Services/TeamGenerationResearchService.php`
- Migration: `database/migrations/002_teamgeneration_research_overview.sql`
- Table: `d11_research_overview_snapshots`

Paste the complete JSON response and explicitly provide its scope metadata. The scope key is required because the JSON itself has no scope identifier. Re-importing identical JSON for the same source/scope is idempotent; changed payloads create new immutable snapshots.

Migration 002 is additive. Fresh installs apply it automatically through the migration runner. Existing installs must run the normal migration command for this PHP site before using the import page.

## Optimizer integration

`TeamGenerationResearchService::optimizerHints($summary)` converts the imported snapshot into optional optimizer hints.

`TeamOptimizerService::generate(..., $allowProvisional, $researchHints)` accepts those hints as its final optional argument. In `grand_league` strategy only, it may apply a small portfolio-level tie-breaker when all 11 selected players have selection percentages and the research sample contains at least 30 matches. The 5-6 patterns are interpreted as low-owned/high-owned because the payload also contains `avgLowOwned` and `avgHighOwned`.

The prior is capped at 1.5% of the lineup selection score. It is not a hard rule and does not override player projections, role/team/credit constraints, or availability. No player-level prediction is changed by this aggregate research.

Role-combination, team-partition, captain-role and role-points arrays are exposed as advisory data only until their index ordering and provider definitions are confirmed.

## Quality checks

```bash
php -l php-site/app/Services/TeamGenerationResearchService.php
php -l php-site/app/Services/TeamOptimizerService.php
php -l php-site/public/admin/engine/index.php
php -d zend.assertions=1 -d assert.exception=1 php-site/tests/teamgeneration_research_test.php
```
