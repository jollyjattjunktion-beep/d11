<?php
declare(strict_types=1);
require dirname(__DIR__, 2) . '/app/bootstrap.php';
require dirname(__DIR__, 2) . '/app/admin_auth.php';
require dirname(__DIR__, 2) . '/app/Services/TeamGenerationSyncService.php';
require dirname(__DIR__, 2) . '/app/Services/Ai11ProfileService.php';
require dirname(__DIR__, 2) . '/app/Services/PlayerPredictionService.php';

$admin = d11_require_admin();
$pdo = d11_db();
$csrf = d11_admin_csrf();
$error = '';
$result = null;
$action = (string)($_POST['action'] ?? '');

function engine_json(string $field): array {
    $raw = (string)($_POST[$field] ?? '');
    if (strlen($raw) > 1048576) throw new RuntimeException('JSON input exceeds 1 MB.');
    $value = json_decode($raw, true, 64, JSON_THROW_ON_ERROR);
    if (!is_array($value)) throw new RuntimeException('JSON input must be an object or list.');
    return $value;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    try {
        if (!d11_admin_check_csrf()) throw new RuntimeException('Security token expired. Refresh and retry.');
        if ($action === 'teamgeneration') {
            $fixture = engine_json('fixture_json');
            $squads = engine_json('squads_json');
            if (array_is_list($fixture) || !array_is_list($squads)) throw new RuntimeException('Fixture must be an object and squads must be a list.');
            $result = (new \D11\Services\TeamGenerationSyncService($pdo))->sync($fixture, $squads);
        } elseif ($action === 'ai11') {
            $matchId = filter_input(INPUT_POST, 'match_id', FILTER_VALIDATE_INT);
            $profiles = engine_json('profiles_json');
            if (!$matchId || !array_is_list($profiles)) throw new RuntimeException('Enter a valid existing match ID and a profiles list.');
            $result = (new \D11\Services\Ai11ProfileService($pdo))->sync((int)$matchId, $profiles);
        } elseif ($action === 'predict') {
            $matchId = filter_input(INPUT_POST, 'match_id', FILTER_VALIDATE_INT);
            if (!$matchId) throw new RuntimeException('Enter a valid match ID.');
            $result = (new \D11\Services\PlayerPredictionService($pdo))->savePredictions((int)$matchId);
        } else {
            throw new RuntimeException('Unknown engine action.');
        }
    } catch (Throwable $e) {
        $error = $e->getMessage();
        error_log('D11 engine admin: ' . $e->getMessage());
    }
}
$matches = $pdo->query('SELECT id, match_title, start_time_utc FROM matches ORDER BY start_time_utc DESC, id DESC LIMIT 100')->fetchAll();
$fixtureExample = [
    'external_id'=>'TG-MATCH-ID','title'=>'Team A vs Team B, 1st T20','format'=>'T20','status'=>'scheduled',
    'start_time_utc'=>'2026-11-20 14:00:00',
    'team_a'=>['external_id'=>'TG-TEAM-A','name'=>'Team A','short_name'=>'A'],
    'team_b'=>['external_id'=>'TG-TEAM-B','name'=>'Team B','short_name'=>'B']
];
$squadExample = [
    ['team_external_id'=>'TG-TEAM-A','player'=>['external_id'=>'TG-PLAYER-1','name'=>'Player One'],'role'=>'BAT','credits'=>9.0,'selection_pct'=>72.5,'status'=>'probable'],
    ['team_external_id'=>'TG-TEAM-B','player'=>['external_id'=>'TG-PLAYER-2','name'=>'Player Two'],'role'=>'BOWL','credits'=>8.5,'selection_pct'=>38.0,'status'=>'playing_xi']
];
$profileExample = [
    ['name'=>'Player One','source_player_id'=>'AI11-PLAYER-1','profile_url'=>'https://www.ai11.in/cricket/player/example','ai11_statistics'=>['matches'=>20,'batting_average'=>31.5,'batting_strike_rate'=>135.0],'ai11_selection_pct'=>63.2,'ai11_captain_pct'=>12.0,'ai11_vice_captain_pct'=>9.0]
];
?><!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>D11 Engine Operations</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#071522;color:#edf5fb;font:15px/1.55 system-ui}header{background:#0d2639;padding:16px max(18px,calc((100% - 1100px)/2));display:flex;justify-content:space-between;gap:12px}a{color:#b7e56b;text-decoration:none}main{max-width:1100px;margin:26px auto;padding:0 16px}.muted{color:#9bb1c2}.panel{background:#10283b;border:1px solid #28485f;border-radius:14px;padding:18px;margin:16px 0}label{display:block;margin:12px 0 5px;color:#c9d9e5}input,textarea,select{width:100%;padding:11px;border-radius:8px;border:1px solid #34536a;background:#081b2b;color:#edf5fb;font:inherit}textarea{min-height:180px;font:13px/1.5 ui-monospace,monospace}button{background:#b7e56b;border:0;border-radius:8px;padding:12px 16px;font-weight:800;margin-top:12px;cursor:pointer}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.error{background:#5a2028;padding:12px;border-radius:8px}.result{white-space:pre-wrap;overflow:auto;background:#06111c;padding:14px;border-radius:8px;font:13px/1.5 monospace}@media(max-width:700px){.grid{grid-template-columns:1fr}}
</style></head><body>
<header><strong>D11 · Engine Operations</strong><span><a href="/admin/dashboard/">Dashboard</a> · <a href="/admin/importer/">Importer</a></span></header>
<main><h1>Fantasy engine operations</h1><p class="muted">TeamGeneration owns fixture and squad data. AI11 only enriches existing squad members. Predictions require imported historical match records.</p>
<?php if($error!==''):?><div class="error"><?=d11_e($error)?></div><?php endif;?>
<?php if($result!==null):?><section class="panel"><h2>Operation result</h2><pre class="result"><?=d11_e(json_encode($result,JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES) ?: '')?></pre></section><?php endif;?>
<section class="panel"><h2>1. Sync TeamGeneration fixture and squad</h2><p class="muted">Re-import updates the same fixture using its stable TeamGeneration external ID. Manually locked squad rows are retained.</p>
<form method="post"><input type="hidden" name="csrf" value="<?=d11_e($csrf)?>"><input type="hidden" name="action" value="teamgeneration">
<div class="grid"><div><label>Fixture JSON</label><textarea name="fixture_json" required><?=d11_e(json_encode($fixtureExample,JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES))?></textarea></div><div><label>Squad JSON</label><textarea name="squads_json" required><?=d11_e(json_encode($squadExample,JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES))?></textarea></div></div><button type="submit">Sync fixture and squad</button></form></section>
<section class="panel"><h2>2. Enrich existing match with AI11 profiles</h2><p class="muted">AI11 player names are linked only when the normalized name uniquely matches a TeamGeneration player in that match. Unmatched and ambiguous names are reported, not inserted into the squad.</p>
<form method="post"><input type="hidden" name="csrf" value="<?=d11_e($csrf)?>"><input type="hidden" name="action" value="ai11"><label>Existing match</label><select name="match_id" required><option value="">Select match</option><?php foreach($matches as $m):?><option value="<?=$m['id']?>">#<?=$m['id']?> · <?=d11_e($m['match_title'])?></option><?php endforeach;?></select><label>AI11 profiles JSON</label><textarea name="profiles_json" required><?=d11_e(json_encode($profileExample,JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES))?></textarea><button type="submit">Link AI11 profiles</button></form></section>
<section class="panel"><h2>3. Generate player predictions</h2><p class="muted">Numeric expected/floor/ceiling projections are withheld until a player has at least three format-matched historical fantasy-point records.</p>
<form method="post"><input type="hidden" name="csrf" value="<?=d11_e($csrf)?>"><input type="hidden" name="action" value="predict"><label>Existing match</label><select name="match_id" required><option value="">Select match</option><?php foreach($matches as $m):?><option value="<?=$m['id']?>">#<?=$m['id']?> · <?=d11_e($m['match_title'])?></option><?php endforeach;?></select><button type="submit">Generate and save predictions</button></form></section>
</main></body></html>