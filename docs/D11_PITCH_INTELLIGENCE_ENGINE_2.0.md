# D11 Pitch Intelligence Engine 2.0

## Product objective

Build one integrated, evidence-aware fantasy-cricket decision engine from four modules. Recommend a repeatable 11-player core, controlled alternatives, four batting opportunities, and bowlers with strong wicket-taking workload. Preserve Dream11 legality and explain each selection and rejection. This is decision support, not a guarantee. Ranking indices are not probabilities or fantasy points.

## Four connected modules

### 1. Pitch & Venue Intelligence
Use only the current match format's venue sample. Combine sourced pitch description, batting/pace/spin suitability, first/second-innings averages, batting-first/bowling-first results, toss, dew, weather and head-to-head when available. Report sample size, source, confidence and missing evidence. Never infer pace/spin indices from a generic venue label. Keep pitch type and innings/toss recommendation distinct.

### 2. Player Opportunity Intelligence
Build role-aware opportunity profiles using confirmed status, expected batting position, expected overs, batting/bowling skill, source involvement, historical player-at-venue evidence, matchup and innings context.
- Top four batters: rank eligible BAT/WK/AR candidates primarily by evidenced batting position (openers and No. 3/4), batting skill/form, expected involvement, venue and matchup. Return up to four, with rank, score, confidence, components and reasons.
- Full-workload wicket-taking bowlers: rank BOWL/AR candidates by expected workload relative to format limits (T20=4 overs, ODI=10 overs; use a Test-specific innings workload, not T20 limits), powerplay/middle/death role, bowling skill, historical wicket rate/strike rate/average, pitch fit and matchup. Flag full allocation only when evidence supports it. Full overs alone do not guarantee wickets.
- Missing expected batting positions/overs remain unknown. Do not fabricate them. Mark low confidence and source coverage.

### 3. Dream11 Structure & Selection Intelligence
Respect contest rules supplied to the request: team size, credits, role min/max, max players from one side and team split. Compare popularity/selection percentage with independent role/opportunity/performance evidence. Classify players:
- Popular + high opportunity: core candidate.
- Low popularity + high opportunity: differential/rotation candidate.
- Popular + low opportunity: popularity trap / review.
- Low popularity + low opportunity: generally avoid unless scenario/rules justify.
Selection percentage and C/VC trends are supporting context, never the primary performance model. Preserve verified credit and playing-status requirements.

### 4. Team Portfolio & Rotation Intelligence
Separate manual locks from automatic core:
- Manual locks: user explicitly chooses 4–5; never silently alter them. Validate status, credits, role quotas, side limits and team split.
- Automatic shared core: high-confidence, multi-signal players using opportunity/performance, not ownership alone.
- Portfolio target: configurable common-XI target of 70–90% (normally 8–10 of 11 shared players). This is a target, not a hard promise. For N teams, target common players = round(target_pct * 11). Report target and achieved overlap. Do not force overlap when evidence, credits, role quotas, confirmed XI, team split or quality make it illegal or weak.
- Remaining 1–3 slots rotate among high-upside differentials, scenario fits, specialist batters and full-workload wicket-taking bowlers. Rotate C/VC separately.
- One team has no portfolio overlap metric. For multiple teams report pairwise/average/maximum overlap and per-player exposure.
- Never make weak picks to hit diversity. Never mislabel 4–5 manual locks as the entire 70–90% core.

## Required additive API result

Attach a versioned `pitch_intelligence_engine` object while preserving current response fields:
- `engine_version: 2.0` and readiness/evidence status for all four modules.
- `venue`: pitch classification, innings/toss tendencies, format sample, sources and confidence.
- `batting_shortlist`: up to four candidates with id/name/team/role/position/opportunity score/confidence/evidence/warnings.
- `wicket_bowling_shortlist`: candidates with expected overs, format maximum, workload percentage, phase roles, bowling skill, wicket evidence, pitch fit, confidence and reasons; explicitly flag verified full-workload candidates.
- `dream11_structure`: popularity/opportunity quadrant, role composition, side split, credits and popularity-trap warnings.
- `portfolio`: manual locks, automatic core, target common percentage/count, achieved overlap, rotation slots/pools, exposure and reasons the target could not be reached.
- `diagnostics`: selection/rejection reasons, high-potential alternatives, all-rounder overload, underrepresented wicket-taking bowling, C/VC ceiling checks and missing data/rule conflicts.

## Current code findings

- `app/venue_analysis.py` analyses format-matched venue profiles and squad strength, but does not create batting-four or bowling-workload shortlists.
- `app/predictor.py` provides a format-specific recency-weighted statistical baseline. It correctly leaves expected/floor/ceiling points null with fewer than three valid history records. AI11 career/series values remain supporting evidence, not fantasy points.
- `app/ai11_analysis.py` supplies batting/bowling skill, series form, popular core and differential recommendations. Current top-level ranks are skill ranks, not full workload/opportunity ranks.
- `app/optimizer.py` already scores batting position and expected overs, validates legal teams, explains selections/rejections and reports exposure. It optimizes diversity with quality floors and overlap penalties, but has no explicit common-core target.
- `app/main.py` passes source profile batting position and expected overs into generation. Its venue-suggestion endpoint currently filters at >=80% selection and sorts largely by selection percentage; replace this with opportunity/performance-aware shortlist logic. Do not require all fixed/core players to exceed 80% popularity.
- The current match-page Smart UI asks for exactly 4–5 manually locked players. Retain this as manual locks, but distinguish these from automatic core and rotation.
- Use verified source fields only. Preserve source attribution. Team Generation already provides batting position and expected overs; make them available to venue/pitch intelligence as well.

## Scoring design

Use normalized explainable components; omit missing data and renormalize remaining evidence weights. Keep separate scores for batting opportunity, bowling workload/opportunity, wicket-taking skill/evidence, fantasy-points expectation (only with adequate format-matched history), popularity/ownership, and overall selection priority. Do not collapse everything into one opaque score. Venue effect is bounded and must not double-count adjustments already applied by predictor.

## Acceptance tests

1. All four modules appear in an integrated result and mark unavailable evidence explicitly.
2. A synthetic T20 pool returns the four best evidence-backed top-order batting opportunities.
3. A sourced four-over bowler with strong wicket evidence ranks above a comparable two-over bowler; unsupported overs stay null.
4. ODI workload uses a 10-over denominator, not T20's four-over denominator.
5. Popularity alone cannot displace a materially higher-opportunity player from strongest/core ranking.
6. Low-ownership, high-opportunity players appear as differentials.
7. Four or five manual locks are preserved and all Dream11 constraints remain enforced.
8. Multi-team portfolio reports 70%, 80%, 90% targets as 8, 9, 10 shared players in an 11-player XI, plus achieved overlap and reasons when unmet.
9. Portfolio generation never violates credits, role, side maximum, confirmed XI or team split.
10. Diagnostics explain high-potential rejections, all-rounder overload, missed specialist bowling and captain-ceiling mismatch.
11. Existing API fields/tests remain backward-compatible.
12. Fantasy-point estimates remain null when history is insufficient; no invented points.

## Delivery sequence

1. Add pure, testable opportunity, shortlist and ownership-quadrant helpers.
2. Add integrated Engine 2.0 service and attach it to venue suggestions and generation response.
3. Add configurable portfolio common-core target without weakening legal validation.
4. Update match-page UI with manual locks, automatic core, rotation pool, exposure/overlap and batter/bowler insights.
5. Add unit/API/UI tests and run the full suite before merging.