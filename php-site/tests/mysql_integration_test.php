<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/Database/MigrationRunner.php';
require dirname(__DIR__) . '/app/Services/TeamGenerationSyncService.php';
require dirname(__DIR__) . '/app/Services/Ai11ProfileService.php';
require dirname(__DIR__) . '/app/Services/PlayerPredictionService.php';
require dirname(__DIR__) . '/app/Services/MatchIntelligenceService.php';
require dirname(__DIR__) . '/app/Services/HistoricalStatsService.php';

use D11\Database\MigrationRunner;
use D11\Services\TeamGenerationSyncService;
use D11\Services\Ai11ProfileService;
use D11\Services\MatchIntelligenceService;
use D11\Services\HistoricalStatsService;
use D11\Services\PlayerPredictionService;

$host = getenv('D11_TEST_DB_HOST') ?: '127.0.0.1';
$name = getenv('D11_TEST_DB_NAME') ?: 'd11_php_test';
$user = getenv('D11_TEST_DB_USER') ?: 'root';
$pass = getenv('D11_TEST_DB_PASSWORD') ?: 'root';
$pdo = new PDO("mysql:host={$host};dbname={$name};charset=utf8mb4", $user, $pass, [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
]);

$schema = file_get_contents(dirname(__DIR__) . '/database/schema.sql');
if ($schema === false) throw new RuntimeException('Cannot read base schema.');
foreach (MigrationRunner::splitSql($schema) as $statement) $pdo->exec($statement);

$migrations = new MigrationRunner($pdo, dirname(__DIR__) . '/database/migrations');
$first = $migrations->run();
$second = $migrations->run();
if (count($first['applied']) !== 1 || count($second['skipped']) !== 1) {
    throw new RuntimeException('Migrations must apply once and be skipped on the second run.');
}

$sync = new TeamGenerationSyncService($pdo);
$fixture = [
    'external_id' => 'CI-FIXTURE-001',
    'title' => 'Test XI vs Test Lions, T20',
    'format' => 'T20',
    'status' => 'scheduled',
    'start_time_utc' => '2026-11-20 10:00:00',
    'team_a' => ['external_id' => 'CI-TEAM-A', 'name' => 'Test XI', 'short_name' => 'TXI'],
    'team_b' => ['external_id' => 'CI-TEAM-B', 'name' => 'Test Lions', 'short_name' => 'TL'],
];
$squads = [
    ['team_external_id' => 'CI-TEAM-A', 'player' => ['external_id' => 'CI-PLAYER-1', 'name' => 'A Player'], 'role' => 'BAT', 'credits' => 9.0, 'selection_pct' => 75.0, 'status' => 'playing_xi'],
    ['team_external_id' => 'CI-TEAM-B', 'player' => ['external_id' => 'CI-PLAYER-2', 'name' => 'B Player'], 'role' => 'BOWL', 'credits' => 8.5, 'selection_pct' => 40.0, 'status' => 'probable'],
];
$one = $sync->sync($fixture, $squads);
$two = $sync->sync($fixture, $squads);
if ($one['match_id'] !== $two['match_id'] || $two['squad_created'] !== 0) {
    throw new RuntimeException('TeamGeneration re-import must update the existing fixture and squad.');
}

$matchId = (int)$one['match_id'];
$lock = $pdo->prepare('UPDATE match_squads SET is_manually_locked = 1, credits = 10.0 WHERE match_id = ? AND player_id = (SELECT id FROM players WHERE external_source = ? AND external_id = ?)');
$lock->execute([$matchId, 'TEAMGENERATION', 'CI-PLAYER-1']);
$changed = $squads;
$changed[0]['credits'] = 7.0;
$lockedResult = $sync->sync($fixture, $changed);
$credit = $pdo->prepare('SELECT ms.credits FROM match_squads ms INNER JOIN players p ON p.id = ms.player_id WHERE ms.match_id = ? AND p.external_id = ?');
$credit->execute([$matchId, 'CI-PLAYER-1']);
if ((float)$credit->fetchColumn() !== 10.0 || $lockedResult['squad_locked_preserved'] !== 1) {
    throw new RuntimeException('Manual squad lock and credits must survive TeamGeneration re-import.');
}

$ai11 = new Ai11ProfileService($pdo);
$result = $ai11->sync($matchId, [
    ['name' => 'A Player', 'source_player_id' => 'AI11-PLAYER-1', 'profile_url' => 'https://www.ai11.in/player/a', 'ai11_statistics' => ['matches' => 20, 'batting_average' => 36, 'batting_strike_rate' => 140]],
    ['name' => 'Not In Squad', 'source_player_id' => 'AI11-UNMATCHED', 'profile_url' => 'https://www.ai11.in/player/missing'],
]);
if ($result['profiles_linked'] !== 1 || $result['unmatched_count'] !== 1) {
    throw new RuntimeException('AI11 must link the matched squad player and report the unmatched player.');
}
$count = (int)$pdo->query("SELECT COUNT(*) FROM match_squads WHERE match_id = {$matchId}")->fetchColumn();
if ($count !== 2) throw new RuntimeException('AI11 must never create selectable squad players.');

// Three historical T20 fantasy records unlock a numeric projection for A Player.
$playerQ = $pdo->prepare('SELECT id FROM players WHERE external_source = ? AND external_id = ?');
$playerQ->execute(['TEAMGENERATION', 'CI-PLAYER-1']);
$playerId = (int)$playerQ->fetchColumn();
for ($i = 1; $i <= 3; $i++) {
    $pastId = 'CI-HISTORY-' . $i;
    $pastSlug = 'ci-history-' . $i;
    $insertMatch = $pdo->prepare('INSERT INTO matches (match_title, slug, format, d11_format, status, external_source, external_id) VALUES (?, ?, ?, ?, ?, ?, ?)');
    $insertMatch->execute(['Historical match ' . $i, $pastSlug, 'T20', 'T20', 'completed', 'CI_HISTORY', $pastId]);
    $historyMatchId = (int)$pdo->lastInsertId();
    $insertStats = $pdo->prepare('INSERT INTO player_match_stats (match_id, player_id, format, fantasy_points, match_date, source) VALUES (?, ?, ?, ?, ?, ?)');
    $insertStats->execute([$historyMatchId, $playerId, 'T20', 40 + ($i * 5), '2026-10-' . (10 + $i), 'CI_TEST']);
}
$intelligence = new MatchIntelligenceService($pdo);
$intelligenceResult = $intelligence->save($matchId, ['batting_friendly'=>0.7, 'pace_friendly'=>0.55, 'rain_probability'=>10, 'dew_likely'=>false, 'pitch_report'=>'Test surface']);
if (!$intelligenceResult['updated'] || $intelligence->get($matchId)['pitch_report'] !== 'Test surface') {
    throw new RuntimeException('Match intelligence must validate and persist.');
}

$historyService = new HistoricalStatsService($pdo);
$historyRecord = ['match_id'=>$matchId, 'player_id'=>$playerId, 'format'=>'T20', 'fantasy_points'=>51, 'runs'=>32, 'balls'=>20, 'match_date'=>'2026-11-19'];
$historyOne = $historyService->import([$historyRecord], 'CI_HISTORY');
$historyTwo = $historyService->import([$historyRecord], 'CI_HISTORY');
if ($historyOne['created'] !== 1 || $historyTwo['updated'] !== 1) {
    throw new RuntimeException('Historical stats import must be idempotent.');
}

$predictionService = new PlayerPredictionService($pdo);
$predictions = $predictionService->predictMatch($matchId);
$predictionA = array_values(array_filter($predictions, fn($p) => (int)$p['player_id'] === $playerId))[0] ?? null;
if (!$predictionA || $predictionA['matches_used'] !== 3 || $predictionA['expected_points'] === null) {
    throw new RuntimeException('PHP predictor must produce a format-matched estimate after three history records.');
}
if (!in_array('Playing status confirmed', $predictionA['reasons'], true)) {
    throw new RuntimeException('TeamGeneration playing_xi status must be treated as confirmed availability.');
}
if ($predictionA['model_version'] !== PlayerPredictionService::MODEL_VERSION) {
    throw new RuntimeException('PHP predictor model version must be explicit.');
}
$saved = $predictionService->savePredictions($matchId);
if (count($saved) !== 2) throw new RuntimeException('Prediction save must return all squad player records, including provisional ones.');


echo "PHP MySQL integration tests passed.\n";
