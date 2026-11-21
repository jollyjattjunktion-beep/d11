# D11 Advanced AI Pitch Intelligence

Target branch: `feature/php-advanced-pitch-intelligence`  
PHP integration: `php-site/app/Services/PitchIntelligenceService.php` → `PlayerPredictionService.php`

## Design principles

1. Match format is normalized before venue statistics are evaluated (T20I/WT20I → T20, WODI → ODI).
2. Venue history is a contextual feature, not a deterministic match prediction.
3. Small samples are shrunk towards neutral; a 12-match record must not create a high-confidence toss or pitch claim.
4. Pace/spin suitability is calculated only when actual pace/spin wicket splits are imported. No inference from total wickets or a text label alone.
5. Batting suitability is calculated against a supplied same-format competition baseline. If no baseline exists, the raw average is displayed but is not converted into a batting-friendly score.
6. Weather, dew and toss remain match-specific inputs, not permanent venue properties.
7. Existing player projections remain bounded; pitch context adjusts expected/floor/ceiling points modestly and does not replace player form or role/involvement evidence.

## Input contract

Save the following structure inside `matches.d11_intelligence_json` using `MatchIntelligenceService::save()`:

```json
{
  "venue_history": {
    "total_matches": 12,
    "matches_won_batting_first": 5,
    "matches_won_bowling_first": 7,
    "average_first_innings_score": 131,
    "average_second_innings_score": 128,
    "tournament_average_first_innings": 145,
    "pace_wickets": 0,
    "spin_wickets": 0,
    "total_bowling_wickets": 0,
    "recent_matches": []
  },
  "dew_likely": false,
  "rain_probability": 10,
  "toss": {
    "winner": "Team A",
    "decision": "bowl"
  }
}
```

Only provide `tournament_average_first_innings` when it is a genuine same-format and preferably same-gender competition baseline. Omit unavailable pace/spin counts instead of sending zero; zero means the source explicitly recorded zero wickets of that type.

## Calculation methodology

### Sample reliability

`reliability = clamp(total_matches / 30, 0, 1)`

Confidence: low below 15 matches, medium from 15 to 29, high at 30 or more. This is evidence coverage, not a probability that a pitch label is correct.

### Toss / innings outcome

Apply a Beta(4,4) prior:

`bat_first_rate = (bat_first_wins + 4) / (decided_matches + 8)`

`bowl_first_rate = (bowl_first_wins + 4) / (decided_matches + 8)`

A toss recommendation is only produced at 15+ venue matches and a smoothed rate of at least 60%.

For the supplied 12-match sample: batting-first = 45.0%, bowling-first = 55.0% after shrinkage. This is a weak chasing lean, not a strong toss call.

### Innings scoring balance

`gap_pct = (first_innings_average - second_innings_average) / second_innings_average * 100`

A 131 versus 128 average is a 2.34% gap. That is not enough, by itself, to label the surface batting- or bowling-friendly.

### Batting suitability

When a valid same-format baseline is supplied:

`raw = clamp(0.5 + ((venue_first_avg / competition_first_avg) - 1) / 0.30)`

`batting_friendly = 0.5 + (raw - 0.5) * reliability`

Without that baseline, the engine does not invent a batting index.

### Pace / spin suitability

Use actual wickets by bowling type divided by all classified bowling wickets. The share is reliability-adjusted towards 0.5. If split data is absent, the corresponding index remains null and no pace/spin adjustment is applied.

### Recent form

The engine can report a recent first-innings average from up to five supplied recent venue matches. It does not silently blend incomplete recent rows into long-run pace/spin or batting scores.

## Predictor integration

`PlayerPredictionService::predictMatch()` analyses venue context once per match, merges only the evidence-backed normalized adjustment fields, and passes them to the existing bounded role-aware condition function:

- BAT/WK: batting suitability.
- BOWL/AR: pace and spin suitability when available.
- BOWL/AR: existing dew adjustment.
- All roles: existing rain-risk adjustment.

The prediction payload includes `pitch_intelligence` and explanatory reasons. The current player-history threshold (at least three format-matched fantasy-point records for numeric projections) remains unchanged.

## Test

Run:

```bash
php -d zend.assertions=1 -d assert.exception=1 php-site/tests/pitch_intelligence_test.php
php -l php-site/app/Services/PitchIntelligenceService.php
php -l php-site/app/Services/PlayerPredictionService.php
```

The current 12-match example should produce low confidence, a 45%/55% shrunk innings-result split, a balanced/undetermined scoring classification, and null pace/spin indices when no wicket-type splits are supplied.
