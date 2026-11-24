<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/Services/TeamOptimizerService.php';

use D11\Services\TeamOptimizerService;

$players = [];
$rolePool = [
    'WK' => 2,
    'BAT' => 7,
    'AR' => 6,
    'BOWL' => 7,
];
$index = 0;
foreach ($rolePool as $role => $count) {
    for ($i = 1; $i <= $count; $i++) {
        $index++;
        $id = $role . $i;
        $players[] = [
            'player_id' => $id,
            'player_name' => $id,
            'team' => ($index % 2 === 0) ? 'B' : 'A',
            'role' => $role,
            'credits' => 8.5,
            'expected_points' => 45 + ($index % 7),
            'floor_points' => 20,
            'ceiling_points' => 80 + ($index % 7),
            'consistency' => 0.6,
            'status' => 'playing_xi',
            'selection_pct' => 30 + ($index % 5) * 10,
        ];
    }
}

$engine = new TeamOptimizerService();
$expectedFormations = [
    '1-3-4-3',
    '1-3-3-4',
    '1-2-4-4',
    '2-3-3-3',
    '1-4-3-3',
    '1-3-2-5',
    '2-3-2-4',
    '2-2-4-3',
];

foreach ($expectedFormations as $offset => $formation) {
    $result = $engine->generate(
        $players,
        [],
        'balanced',
        [],
        [],
        null,
        null,
        true,
        [],
        ['rotation_offset' => $offset]
    );

    if ($result['formation'] !== $formation) {
        throw new RuntimeException("Rotation offset {$offset} expected {$formation}, got " . (string)$result['formation']);
    }
    if (count($result['players']) !== 11) throw new RuntimeException('Formation must produce exactly eleven players.');
    if ($result['role_counts'] !== $result['formation_role_counts']) throw new RuntimeException('Selected role counts must match the exact formation.');
    if ($result['total_credits'] > 100.0) throw new RuntimeException('Credit cap exceeded.');
    if (max($result['team_split']) > 7) throw new RuntimeException('Maximum players from one team exceeded.');
    if ($result['captain_id'] === $result['vice_captain_id']) throw new RuntimeException('Captain and vice-captain must differ.');
    if (abs($result['diagnostics']['non_core_variation_points']) > 3.2) throw new RuntimeException('Non-core variation exceeded +/-3.2 points.');
    if ($result['diagnostics']['fixed_core_preserved'] !== true) throw new RuntimeException('Fixed core preservation diagnostic missing.');
}

$lockedResult = $engine->generate(
    $players,
    [],
    'balanced',
    ['WK1', 'BAT1'],
    [],
    null,
    null,
    true,
    [],
    ['rotation_offset' => 2]
);
$lockedIds = array_column($lockedResult['players'], 'player_id');
if (!in_array('WK1', $lockedIds, true) || !in_array('BAT1', $lockedIds, true)) {
    throw new RuntimeException('The fixed core must remain in the selected XI.');
}
if ($lockedResult['formation'] !== '1-2-4-4') {
    throw new RuntimeException('The locked-core fixture should still support the requested formation.');
}

// Explicit caller-provided minimum role rules remain respected by default.
$minRoleResult = $engine->generate(
    $players,
    ['min_role' => ['WK'=>1,'BAT'=>3,'AR'=>1,'BOWL'=>3]],
    'balanced',
    [],
    [],
    null,
    null,
    true,
    [],
    ['rotation_offset' => 2]
);
if (($minRoleResult['role_counts']['BAT'] ?? 0) < 3) {
    throw new RuntimeException('Explicit minimum batter-role constraint was not preserved.');
}

// Legacy mode remains available for non-formation integrations.
$legacy = $engine->generate(
    $players,
    [],
    'balanced',
    [],
    [],
    null,
    null,
    true,
    [],
    ['enabled' => false]
);
if (count($legacy['players']) !== 11 || $legacy['formation'] !== null) {
    throw new RuntimeException('Legacy optimizer mode should remain available.');
}

$failed = false;
try {
    $engine->generate($players, [], 'balanced', [], [], null, null, true, [], ['variation_points' => 3.21]);
} catch (InvalidArgumentException) {
    $failed = true;
}
if (!$failed) throw new RuntimeException('Variation above 3.2 must be rejected.');

echo "Randomized tactical formation tests passed.\n";
