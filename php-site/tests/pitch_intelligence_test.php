<?php
declare(strict_types=1);

require_once __DIR__ . '/../app/Services/PitchIntelligenceService.php';

use D11\Services\PitchIntelligenceService;

$engine = new PitchIntelligenceService();
$result = $engine->analyse([
    'venue_history' => [
        'total_matches' => 12,
        'matches_won_batting_first' => 5,
        'matches_won_bowling_first' => 7,
        'average_first_innings_score' => 131,
        'average_second_innings_score' => 128,
    ],
], 'WT20');

assert($result['format'] === 'T20');
assert($result['confidence'] === 'low');
assert($result['batting_first_win_pct'] === 45.0); // Beta(4,4) shrinkage
assert($result['bowling_first_win_pct'] === 55.0);
assert($result['pitch_type'] === 'balanced'); // 3-run gap is not enough to call it bowling-friendly
assert($result['pace_friendly'] === null);
assert($result['spin_friendly'] === null);
assert(!isset($result['adjustments']['pace_friendly']));
assert(!isset($result['adjustments']['spin_friendly']));

$withEvidence = $engine->analyse([
    'venue_history' => [
        'total_matches' => 30,
        'matches_won_batting_first' => 18,
        'matches_won_bowling_first' => 12,
        'average_first_innings_score' => 160,
        'average_second_innings_score' => 145,
        'tournament_average_first_innings' => 145,
        'pace_wickets' => 42,
        'spin_wickets' => 28,
        'total_bowling_wickets' => 70,
    ],
], 'T20');

assert($withEvidence['pitch_type'] === 'batting');
assert($withEvidence['batting_friendly'] > 0.5);
assert($withEvidence['pace_friendly'] > 0.5);
assert($withEvidence['spin_friendly'] < 0.5);
assert($withEvidence['toss_recommendation'] === 'bat');

$missing = $engine->analyse([], 'T20');
assert($missing['available'] === false);
assert($missing['pitch_type'] === 'insufficient_data');
assert($missing['adjustments'] === []);

echo "Pitch intelligence tests passed.\n";
