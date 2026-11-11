<?php
declare(strict_types=1);

require dirname(__DIR__) . '/app/bootstrap.php';

$pdo = d11_db();
$counts = [];
foreach (['competitions','series','teams','players','venues','matches'] as $table) {
    $counts[$table] = (int)$pdo->query("SELECT COUNT(*) FROM `{$table}`")->fetchColumn();
}
$recent = $pdo->query("SELECT id, match_title, status, start_time_utc FROM matches ORDER BY start_time_utc DESC LIMIT 8")->fetchAll();
?><!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title><?=d11_e($config['app_name'] ?? 'D11 Cricket')?> — Cricket Data Centre</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#071522;color:#eef5fa;font:15px/1.5 system-ui}header{padding:22px max(18px,calc((100% - 1100px)/2));background:#0d2639;border-bottom:1px solid #234258;display:flex;justify-content:space-between;align-items:center}.logo{font-size:25px;font-weight:900}.logo b{color:#a6d64f}main{max-width:1100px;margin:28px auto;padding:0 18px}.muted{color:#9bb1c2}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card{background:#10283b;border:1px solid #24445b;border-radius:14px;padding:18px}.num{font-size:30px;font-weight:800;color:#b7e56b}.section{margin-top:24px}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px;border-bottom:1px solid #284358}th{color:#a9bdcc;font-size:12px;text-transform:uppercase}.empty{padding:28px;text-align:center;color:#a9bdcc}@media(max-width:650px){.grid{grid-template-columns:repeat(2,1fr)}header{padding:18px}}
</style></head><body>
<header><div class="logo"><b>D11</b> CRICKET</div><div class="muted">Cricket Data Centre</div></header>
<main><h1>Cricket data overview</h1><p class="muted">Your installation is connected to MySQL. This phase focuses on collecting and maintaining cricket records before fantasy features are added.</p>
<div class="grid">
<?php foreach (['competitions'=>'Competitions','series'=>'Series','teams'=>'Teams','players'=>'Players','venues'=>'Venues','matches'=>'Matches'] as $key=>$label): ?>
<div class="card"><div class="muted"><?=d11_e($label)?></div><div class="num"><?=number_format($counts[$key])?></div></div>
<?php endforeach; ?>
</div>
<div class="section card"><h2>Recent matches</h2>
<?php if (!$recent): ?><div class="empty">No matches imported yet. The next step is connecting an authorised cricket data source and importing series and fixtures.</div>
<?php else: ?><table><thead><tr><th>Match</th><th>Status</th><th>Start (UTC)</th></tr></thead><tbody>
<?php foreach($recent as $match): ?><tr><td><?=d11_e($match['match_title'])?></td><td><?=d11_e($match['status'])?></td><td><?=d11_e($match['start_time_utc'] ?? 'TBC')?></td></tr><?php endforeach; ?>
</tbody></table><?php endif; ?></div>
<div class="section muted">D11 PHP installation · Fantasy modules are intentionally not included in this phase.</div>
</main></body></html>
