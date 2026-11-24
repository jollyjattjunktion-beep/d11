<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/Services/TeamGenerationResearchService.php';

use D11\Services\TeamGenerationResearchService;

$payload = [
    'totalMatches' => 245,
    'minSample' => false,
    'context' => [
        'winnerKnown' => 239,
        'tossKnown' => 239,
        'tossWonMatchWonPct' => 51.46,
        'tossWonMatchWonCount' => 123,
        'batFirstWonPct' => 48.95,
        'batFirstWonCount' => 117,
        'tossDecision' => ['bat' => 66, 'bowl' => 179],
        'innings' => [
            ['avgScore' => 192.74, 'avgWickets' => 7.13, 'avgTop6' => [33.07,28.04,28.04,28.46,24,16.8]],
            ['avgScore' => 168.47, 'avgWickets' => 6.45, 'avgTop6' => [27.74,27.29,24.9,25.36,17.58,13.94]],
        ],
        'avgPaceWickets' => 7.96,
        'avgSpinWickets' => 4.81,
    ],
    'dreamTeam' => [
        'avgPointsTotal' => 1307.28,
        'avgPointsByRole' => [124.04,267.27,339.67,314.67],
        'captainRolePct' => [11.43,26.94,40.82,20.82],
        'captainRoleCount' => [28,66,100,51],
        'vcRolePct' => [13.47,24.9,37.14,24.49],
        'vcRoleCount' => [33,61,91,60],
        'captainFromWinningPct' => 74.48,
        'captainFromWinningCount' => 178,
        'vcFromWinningPct' => 65.69,
        'vcFromWinningCount' => 157,
        'fixedTopPct' => [68.16,43.67,26.12,17.55,8.16],
        'fixedTopCount' => [167,107,64,43,20],
        'groupTop' => [['label'=>'>=1 of top 2','count'=>223,'pct'=>91.02]],
        'groupBottom' => [['label'=>'<=1 of bottom 2','count'=>209,'pct'=>85.31]],
        'partitionFreq' => [['pattern'=>'6:5','count'=>82,'pct'=>33.47],['pattern'=>'7:4','count'=>76,'pct'=>31.02]],
        'combinationFreq' => [['pattern'=>'1-3-4-3','count'=>18,'pct'=>7.35]],
        'percentageSplitFreq' => [['pattern'=>'5-6','count'=>62,'pct'=>25.31],['pattern'=>'6-5','count'=>51,'pct'=>20.82]],
        'avgLowOwned' => 5.05,
        'avgHighOwned' => 5.95,
        'credit' => ['avgDtCredits'=>89.26,'bandP10'=>84.5,'bandP90'=>92.5],
        'partitionWithinSuggestedPct' => 87.35,
        'partitionWithinSuggestedCount' => 214,
        'percentageWithinSuggestedPct' => 73.36,
        'percentageWithinSuggestedCount' => 179,
        'percentageWithinScored' => 244,
        'combinationWithinSuggestedPct' => 60.41,
        'combinationWithinSuggestedCount' => 148,
    ],
];

$summary = TeamGenerationResearchService::normalizeOverview($payload);
if ($summary['total_matches'] !== 245) throw new RuntimeException('Match sample count was not parsed.');
if ($summary['context']['first_innings']['average_score'] !== 192.74) throw new RuntimeException('First innings average was not parsed.');
if ($summary['context']['second_innings']['average_score'] !== 168.47) throw new RuntimeException('Second innings average was not parsed.');
if (round($summary['context']['first_second_score_difference_pct_of_first'], 2) !== 12.59) throw new RuntimeException('Innings score differential is incorrect.');
if ($summary['dream_team']['captain_from_winning_side_pct'] !== 74.48) throw new RuntimeException('Winning-side captain rate was not parsed.');
if ($summary['dream_team']['role_combination_frequency_unmapped'][0]['pattern'] !== '1-3-4-3') throw new RuntimeException('Role combination pattern was not preserved.');
if ($summary['dream_team']['ownership_percentage_split_frequency'][0]['pattern'] !== '5-6') throw new RuntimeException('Ownership split pattern was not preserved.');
if (!$summary['warnings']) throw new RuntimeException('Expected data-quality warnings for source count/role reconciliation.');

$hints = TeamGenerationResearchService::optimizerHints($summary);
if ($hints['sample_matches'] !== 245) throw new RuntimeException('Optimizer hint sample count missing.');
if ($hints['average_low_owned_players'] !== 5.05) throw new RuntimeException('Ownership guidance missing.');
if (!str_contains($hints['usage'], 'Advisory')) throw new RuntimeException('Hints must be explicitly advisory.');

$failed = false;
try { TeamGenerationResearchService::normalizeOverview(['totalMatches'=>0,'context'=>[],'dreamTeam'=>[]]); }
catch (RuntimeException) { $failed = true; }
if (!$failed) throw new RuntimeException('Invalid overview payload must be rejected.');

$failed = false;
try { TeamGenerationResearchService::normalizeOverview([
    'totalMatches'=>3,'context'=>['tossWonMatchWonPct'=>140],'dreamTeam'=>[]
]); } catch (RuntimeException) { $failed = true; }
if (!$failed) throw new RuntimeException('Out-of-range percentage must be rejected.');

require dirname(__DIR__) . '/app/Services/TeamOptimizerService.php';

$optimizerPlayers = [
    ['player_id'=>'P1','team'=>'A','role'=>'WK','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>20],
    ['player_id'=>'P2','team'=>'B','role'=>'BAT','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>20],
    ['player_id'=>'P3','team'=>'A','role'=>'BAT','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>20],
    ['player_id'=>'P4','team'=>'B','role'=>'BAT','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>80],
    ['player_id'=>'P5','team'=>'A','role'=>'AR','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>80],
    ['player_id'=>'P6','team'=>'B','role'=>'AR','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>20],
    ['player_id'=>'P7','team'=>'A','role'=>'BOWL','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>80],
    ['player_id'=>'P8','team'=>'B','role'=>'BOWL','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>80],
    ['player_id'=>'P9','team'=>'A','role'=>'BOWL','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>20],
    ['player_id'=>'P10','team'=>'B','role'=>'BAT','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>80],
    ['player_id'=>'P11','team'=>'A','role'=>'AR','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>20],
    ['player_id'=>'P12','team'=>'B','role'=>'AR','credits'=>8.0,'expected_points'=>50,'status'=>'playing','selection_pct'=>80],
];
$optimizer = new \D11\Services\TeamOptimizerService();
$locked = ['P1','P2','P3','P4','P5','P6','P7','P8','P9','P10'];
$withoutResearch = $optimizer->generate($optimizerPlayers, [], 'grand_league', $locked, [], null, null, true, [], ['enabled'=>false]);
$withResearch = $optimizer->generate($optimizerPlayers, [], 'grand_league', $locked, [], null, null, true, $hints, ['enabled'=>false]);
if (!in_array('P12', array_column($withResearch['players'], 'player_id'), true)) {
    throw new RuntimeException('Grand League optimizer did not apply the more frequent 5-low/6-high research split.');
}
if (empty($withResearch['diagnostics']['research_ownership_prior_applied'])) {
    throw new RuntimeException('Optimizer diagnostics did not record the applied research prior.');
}
if ($withResearch['diagnostics']['research_ownership_prior_bonus'] <= 0) {
    throw new RuntimeException('Research ownership prior bonus should be positive.');
}
if (in_array('P12', array_column($withoutResearch['players'], 'player_id'), true)) {
    throw new RuntimeException('Baseline optimizer should not consume research hints when none are provided.');
}

echo "TeamGeneration research overview tests passed.\n";